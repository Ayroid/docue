"""The one place the system talks to a model.

Every LLM call in the project goes through `complete_json`, and every embedding
through `embed`. That is deliberate: a single door makes the guarantees
enforceable rather than aspirational -- every call is timed, logged with its
prompt version, and returns a *validated* object rather than free text.

**Historical note on the module name.** This file used to talk to AWS Bedrock
(hence `bedrock.py`, `BedrockError`) via boto3's Converse API. For local
development it now talks to a local OpenAI-API-compatible LLM proxy over
`httpx` instead. The module path and every exported name are kept exactly as
they were so that the eight call sites across the codebase (and the test
script that patches `complete_json` per call site, plus the one that imports
`BedrockError`/`LLMCall` directly) need no changes -- only the internals
below changed. `BedrockError` is therefore a name, not a claim about what
raises it.

The proxy is OpenAI-compatible, so structured output is implemented the same
way OpenAI's API does it: a forced tool/function call. The model is required
to call `emit_result` with arguments matching the schema, and the schema is
handed to it as the tool's JSON-schema `parameters` -- there is no other way
for the model to answer.

**It is not, however, a guarantee about shape.** Different backends behind a
"auto"-routed proxy can still return oddly-encoded tool arguments (the
Bedrock-era version of this file documented the same problem against
Anthropic's Converse API). `_unwrap` below repairs the shapes seen in
practice; every caller must still parse defensively.
"""

import json
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

__all__ = [
    "BedrockError",
    "LLMCall",
    "complete_json",
    "embed",
    "get_runtime",
    "last_calls",
]

# The tool the model is forced to call. Structured output is a forced tool
# call rather than a response-format flag: the caller names exactly what it
# expects back, and a malformed reply is not a failure mode it silently
# swallows -- it is either well-formed or an explicit `BedrockError`.
_EMIT_TOOL = "emit_result"


class BedrockError(RuntimeError):
    """A model call failed, or returned something that isn't the shape asked for."""


@dataclass
class LLMCall:
    """One call, timed. `cost_usd` is always 0.0 -- pricing is unknown for a
    free/local proxy, and guessing would be worse than saying so plainly."""

    purpose: str
    model_id: str
    prompt_version: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cost_usd: float
    ok: bool
    error: str | None = None


# Bounded: this is a rolling window for `scripts/` and the run report, not a
# durable ledger. Unbounded, it grew by one entry per model call for the life
# of the process.
_MAX_REMEMBERED_CALLS = 500
_calls: deque[LLMCall] = deque(maxlen=_MAX_REMEMBERED_CALLS)


def last_calls() -> list[LLMCall]:
    """The most recent calls, oldest first, capped at `_MAX_REMEMBERED_CALLS`."""
    return list(_calls)


def _cost(model_id: str, input_tokens: int, output_tokens: int) -> float:
    # Pricing is unknown for a free/local proxy; recorded as 0.0 rather than
    # guessed.
    return 0.0


_runtime: httpx.Client | None = None


def get_runtime() -> httpx.Client:
    """The HTTP client for the local LLM proxy, built once."""
    global _runtime
    if _runtime is None:
        _runtime = httpx.Client(
            base_url=settings.llm_base_url,
            headers={
                "Authorization": f"Bearer {settings.llm_api_key}",
                "Content-Type": "application/json",
            },
            timeout=settings.llm_timeout_seconds,
        )
    return _runtime


def _describe(exc: Exception, model: str) -> str:
    """Turn an httpx error into something that names the fix."""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        body = exc.response.text[:400]
        if status == 401:
            return f"the proxy rejected LLM_API_KEY (401). Check .env. Body: {body}"
        if status == 404:
            return f"model {model!r} not found on the proxy (404). Body: {body}"
        return f"proxy returned HTTP {status} for model {model!r}: {body}"
    return str(exc)[:400]


def complete_json(
    *,
    purpose: str,
    system: str,
    user: str,
    schema: dict[str, Any],
    prompt_version: str,
    max_tokens: int = 8000,
    model_id: str | None = None,
) -> dict[str, Any]:
    """One model call that must return an object matching `schema`.

    The schema is handed to the proxy as a forced OpenAI-style tool call.
    **Every caller must still parse defensively** -- skip entries that are
    not the shape asked for, and count them. See `_unwrap` for what is
    already repaired here.

    Raises `BedrockError` rather than returning a sentinel: every caller has
    a documented non-LLM fallback, and one that silently treated an error as
    an empty result would ship a document with regions quietly dropped.
    """
    model = model_id or settings.llm_chat_model
    started = time.perf_counter()
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": _EMIT_TOOL,
                    "description": "Return the result. This is the only way to answer.",
                    "parameters": schema,
                },
            }
        ],
        "tool_choice": {"type": "function", "function": {"name": _EMIT_TOOL}},
    }
    try:
        response = get_runtime().post("/chat/completions", json=body)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        _record(purpose, model, prompt_version, 0, 0, started, ok=False, error=str(exc))
        raise BedrockError(f"{purpose}: {_describe(exc, model)}") from exc
    except httpx.HTTPError as exc:
        _record(purpose, model, prompt_version, 0, 0, started, ok=False, error=str(exc))
        raise BedrockError(
            f"{purpose}: could not reach LLM proxy at {settings.llm_base_url}: {exc}"
        ) from exc

    usage = payload.get("usage", {})
    _record(
        purpose,
        model,
        prompt_version,
        usage.get("prompt_tokens", 0),
        usage.get("completion_tokens", 0),
        started,
        ok=True,
    )

    choice = (payload.get("choices") or [{}])[0]
    finish_reason = choice.get("finish_reason")
    if finish_reason == "length":
        raise BedrockError(
            f"{purpose}: response hit max_tokens ({max_tokens}) and is truncated. "
            f"Raise max_tokens or split the batch."
        )
    tool_calls = (choice.get("message") or {}).get("tool_calls") or []
    for call in tool_calls:
        if call.get("function", {}).get("name") == _EMIT_TOOL:
            arguments = call["function"].get("arguments", "{}")
            return _unwrap(arguments, schema, purpose)
    raise BedrockError(
        f"{purpose}: the model answered without calling {_EMIT_TOOL} "
        f"(finish_reason={finish_reason})"
    )


def _unwrap(payload: Any, schema: dict[str, Any], purpose: str) -> dict[str, Any]:
    """Decode the tool call's arguments and repair known double-encoding.

    OpenAI's tool-calling API always returns `function.arguments` as a
    JSON-encoded string by spec, so the first branch below (decode a string
    payload) is the normal, expected first step for every single call here --
    not a quirk repair. The nested-string repair loop that follows it is kept
    because different backends behind `"auto"` routing may still double-encode
    array/object fields the way Bedrock's Converse API used to: a schema
    declaring `{"questions": {"type": "array", ...}}` coming back as
    `{"questions": "[{...}]"}`, the array JSON-encoded as a string value.

    Anything that does not decode is returned untouched for the caller's own
    defensive parsing to reject. Every repair is logged.
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return {}
    if not isinstance(payload, dict):
        return {}

    properties = schema.get("properties", {})
    for key, spec in properties.items():
        value = payload.get(key)
        if not isinstance(value, str) or spec.get("type") not in ("array", "object"):
            continue
        try:
            decoded = json.loads(value)
        except ValueError:
            continue
        if isinstance(decoded, dict) and key in decoded:
            decoded = decoded[key]
        payload[key] = decoded
        logger.warning("%s: %r arrived JSON-encoded; decoded it", purpose, key)

    return payload


def embed(texts: list[str], *, purpose: str = "embed", input_type: str = "search_document") -> list[list[float]]:
    """Embed one or more strings.

    `input_type` is accepted-and-ignored: it was a Cohere-specific
    document/query prefix trick used by the old Bedrock embedding model, and
    the local proxy's OpenAI-compatible `/embeddings` endpoint has no
    equivalent concept. Kept on the signature purely so callers (e.g.
    `app/search/hybrid.py`, which passes `input_type="search_query"`) need no
    edit. If retrieval quality suffers from losing that asymmetric embedding,
    that is a real behavior change worth revisiting, not something papered
    over here.
    """
    if not texts:
        return []
    model = settings.llm_embedding_model
    started = time.perf_counter()
    try:
        response = get_runtime().post("/embeddings", json={"model": model, "input": texts})
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        _record(purpose, model, "openai-embeddings/1.0.0", 0, 0, started, ok=False, error=str(exc))
        raise BedrockError(f"{purpose}: {_describe(exc, model)}") from exc
    except httpx.HTTPError as exc:
        _record(purpose, model, "openai-embeddings/1.0.0", 0, 0, started, ok=False, error=str(exc))
        raise BedrockError(
            f"{purpose}: could not reach LLM proxy at {settings.llm_base_url}: {exc}"
        ) from exc

    usage = payload.get("usage", {})
    _record(
        purpose,
        model,
        "openai-embeddings/1.0.0",
        usage.get("prompt_tokens", 0),
        0,
        started,
        ok=True,
    )

    data = sorted(payload.get("data", []), key=lambda item: item.get("index", 0))
    embeddings = [item["embedding"] for item in data]

    if not embeddings or len(embeddings) != len(texts):
        raise BedrockError(f"{purpose}: expected {len(texts)} embeddings, got {len(embeddings or [])}")
    width = len(embeddings[0])
    if width != settings.embedding_dimensions:
        raise BedrockError(
            f"{purpose}: model returned {width}-dimension vectors but the schema expects "
            f"{settings.embedding_dimensions}. Fix `embedding_dimensions`/`llm_embedding_model` "
            f"before any are stored."
        )
    return embeddings


def _record(
    purpose: str,
    model: str,
    prompt_version: str,
    input_tokens: int,
    output_tokens: int,
    started: float,
    *,
    ok: bool,
    error: str | None = None,
) -> None:
    call = LLMCall(
        purpose=purpose,
        model_id=model,
        prompt_version=prompt_version,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=int((time.perf_counter() - started) * 1000),
        cost_usd=_cost(model, input_tokens, output_tokens),
        ok=ok,
        error=error,
    )
    _calls.append(call)
    logger.info(
        "llm %s model=%s prompt=%s in=%d out=%d %dms%s",
        purpose,
        model,
        prompt_version,
        call.input_tokens,
        call.output_tokens,
        call.latency_ms,
        "" if ok else f" FAILED: {error}",
    )
