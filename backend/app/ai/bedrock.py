"""The one place the system talks to a model.

Every LLM call in the project goes through `complete_json`, and every embedding
through `embed`. That is deliberate: plan §10 is a bounded pipeline of narrow
call sites, not an agent with a loose leash, and a single door makes the
guarantees enforceable rather than aspirational -- every call is timed, priced,
logged with its prompt version, and returns a *validated* object rather than
free text.

**Why the `bedrock-runtime` Converse API and not the Anthropic SDK.** Measured
against this account, not chosen by preference: the Anthropic SDK's Mantle
client authenticates fine (SigV4 accepted, real `request_id` returned) but
returns `404 not_found_error` for every model, including ones that
`list_foundation_models` reports. `bedrock-runtime` recognises the same models
and fails only on IAM. So this account is a Bedrock account, not a Claude
Platform one, and Converse is the surface it actually has.

Four environment facts are baked in, each of which cost real time to find:

  * **The model id needs the `us.` inference-profile prefix.** A bare
    `anthropic.claude-sonnet-5` is rejected with "Invocation of model ID ...
    with on-demand throughput isn't supported."
  * **Bedrock authenticates separately from S3.** A Bedrock API key (`ABSK...`)
    is a bearer token read from `AWS_BEARER_TOKEN_BEDROCK`, not an access-key
    pair -- putting it in `AWS_ACCESS_KEY_ID` shadows the S3 credentials and
    authenticates nothing.
  * **Corporate TLS interception breaks botocore** here as everywhere else;
    `app/storage/s3.py::_ca_bundle_path()` is the shared fix. Do not swap it
    for `truststore` -- that was tried and caused `maximum recursion depth
    exceeded`.
  * **A forced tool choice requires thinking to be disabled on Bedrock.**
    That is a Bedrock-specific constraint, and structured output here *is* a
    forced tool, so thinking is off on every call this module makes.
"""

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings
from app.storage.s3 import _ca_bundle_path

logger = logging.getLogger(__name__)

__all__ = [
    "BedrockError",
    "LLMCall",
    "complete_json",
    "embed",
    "get_runtime",
    "last_calls",
]

# Bedrock is partner-operated and prices separately from the first-party API.
# Per 1M tokens, so a run can report what it cost without a lookup.
_PRICE_PER_MTOK = {
    "us.anthropic.claude-sonnet-5": (3.00, 15.00),
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0": (3.00, 15.00),
}

# The tool the model is forced to call. Structured output on Converse is a
# forced tool call rather than a response-format flag: the arguments are
# schema-validated by the API, so a malformed reply is not a failure mode the
# callers have to handle.
_EMIT_TOOL = "emit_result"


class BedrockError(RuntimeError):
    """A model call failed, or returned something that isn't the shape asked for."""


@dataclass
class LLMCall:
    """One call, priced and timed. Plan §8's `llm_calls` row, before there is a table."""

    purpose: str
    model_id: str
    prompt_version: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cost_usd: float
    ok: bool
    error: str | None = None


_calls: list[LLMCall] = []


def last_calls() -> list[LLMCall]:
    return list(_calls)


def _cost(model_id: str, input_tokens: int, output_tokens: int) -> float:
    prices = _PRICE_PER_MTOK.get(model_id)
    if prices is None:
        return 0.0
    return (input_tokens * prices[0] + output_tokens * prices[1]) / 1_000_000


_runtime = None


def get_runtime():
    """The `bedrock-runtime` client, built once.

    No explicit credentials: a Bedrock API key lives in
    `AWS_BEARER_TOKEN_BEDROCK` and botocore picks it up from the environment.
    Passing the S3 access keys here would authenticate as the wrong principal.
    """
    global _runtime
    if _runtime is None:
        _runtime = boto3.client(
            "bedrock-runtime",
            region_name=settings.resolved_bedrock_region,
            verify=_ca_bundle_path(),
            config=Config(
                read_timeout=settings.bedrock_timeout_seconds,
                connect_timeout=15,
                retries={"max_attempts": settings.bedrock_max_retries, "mode": "standard"},
            ),
        )
    return _runtime


def _describe(exc: Exception, model: str) -> str:
    """Turn a botocore error into something that names the fix."""
    text = str(exc)
    if "is not authorized to perform: bedrock:InvokeModel" in text:
        return (
            f"the Bedrock principal lacks `bedrock:InvokeModel` on {model}. This is an IAM "
            f"policy gap, not a credential problem -- the key authenticates, it just cannot "
            f"invoke."
        )
    if "on-demand throughput isn" in text:
        return (
            f"{model} needs a cross-region inference profile id (prefix it with `us.`), "
            f"not a bare foundation-model id."
        )
    return text[:400]


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

    The schema is handed to Bedrock as a forced tool, so the model's arguments
    are validated against it before they reach us. It is also the enforcement
    point for plan §10's contract -- the model emits *values*, never XML, never
    a cell reference, never a file path. What it may name is fixed by the enums
    the caller puts in the schema.

    Raises `BedrockError` rather than returning a sentinel: every caller has a
    documented non-LLM fallback, and one that silently treated an error as an
    empty result would ship a document with regions quietly dropped.
    """
    model = model_id or settings.bedrock_model_id
    started = time.perf_counter()
    try:
        response = get_runtime().converse(
            modelId=model,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": user}]}],
            inferenceConfig={"maxTokens": max_tokens},
            toolConfig={
                "tools": [
                    {
                        "toolSpec": {
                            "name": _EMIT_TOOL,
                            "description": "Return the result. This is the only way to answer.",
                            "inputSchema": {"json": schema},
                        }
                    }
                ],
                "toolChoice": {"tool": {"name": _EMIT_TOOL}},
            },
            # Bedrock rejects a forced tool choice while thinking is on.
            additionalModelRequestFields={"thinking": {"type": "disabled"}},
        )
    except (BotoCoreError, ClientError) as exc:
        _record(purpose, model, prompt_version, 0, 0, started, ok=False, error=str(exc))
        raise BedrockError(f"{purpose}: {_describe(exc, model)}") from exc

    usage = response.get("usage", {})
    _record(
        purpose,
        model,
        prompt_version,
        usage.get("inputTokens", 0),
        usage.get("outputTokens", 0),
        started,
        ok=True,
    )

    if response.get("stopReason") == "max_tokens":
        raise BedrockError(
            f"{purpose}: response hit max_tokens ({max_tokens}) and is truncated. "
            f"Raise max_tokens or split the batch."
        )
    for block in response["output"]["message"]["content"]:
        if "toolUse" in block:
            return block["toolUse"]["input"]
    raise BedrockError(
        f"{purpose}: the model answered without calling {_EMIT_TOOL} "
        f"(stopReason={response.get('stopReason')})"
    )


def embed(texts: list[str], *, purpose: str = "embed", input_type: str = "search_document") -> list[list[float]]:
    """Embed one or more strings.

    `input_type` is not decoration -- Cohere embeds documents and queries into
    the same space using different prefixes, and using `search_document` for a
    query measurably degrades retrieval. Ingestion passes the default; the
    search path must pass `search_query`.
    """
    if not texts:
        return []
    model = settings.bedrock_embedding_model_id
    started = time.perf_counter()
    try:
        response = get_runtime().invoke_model(
            modelId=model,
            body=json.dumps(
                {
                    "texts": texts,
                    "input_type": input_type,
                    "output_dimension": settings.embedding_dimensions,
                    "embedding_types": ["float"],
                }
            ),
        )
    except (BotoCoreError, ClientError) as exc:
        _record(purpose, model, "cohere/embed-v4", 0, 0, started, ok=False, error=str(exc))
        raise BedrockError(f"{purpose}: {_describe(exc, model)}") from exc

    payload = json.loads(response["body"].read())
    embeddings = payload.get("embeddings")
    # v4 returns {"embeddings": {"float": [[...]]}}; older shapes return a bare
    # list. Accept both rather than pinning to one response version.
    if isinstance(embeddings, dict):
        embeddings = embeddings.get("float") or next(iter(embeddings.values()))
    _record(purpose, model, "cohere/embed-v4", 0, 0, started, ok=True)

    if not embeddings or len(embeddings) != len(texts):
        raise BedrockError(f"{purpose}: expected {len(texts)} embeddings, got {len(embeddings or [])}")
    width = len(embeddings[0])
    if width != settings.embedding_dimensions:
        raise BedrockError(
            f"{purpose}: model returned {width}-dimension vectors but the schema expects "
            f"{settings.embedding_dimensions}. Fix `embedding_dimensions` before any are stored."
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
        "llm %s model=%s prompt=%s in=%d out=%d %dms $%.5f%s",
        purpose,
        model,
        prompt_version,
        call.input_tokens,
        call.output_tokens,
        call.latency_ms,
        call.cost_usd,
        "" if ok else f" FAILED: {error}",
    )
