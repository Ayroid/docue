"""The one place the system talks to a model.

Every LLM call in the project goes through `complete_json`. That is deliberate:
plan §10 is a bounded pipeline of nine narrow call sites, not an agent with a
loose leash, and a single door makes the guarantees enforceable rather than
aspirational -- every call is timed, priced, logged with its prompt version, and
returns a *validated* object rather than free text.

Three environment facts are baked in, each of which cost real time to find:

  * **Bedrock needs its own credentials.** The key that reaches S3 has
    `s3:*` but not `bedrock:InvokeModel` -- listing models works and invoking
    returns `AccessDeniedException`. `config.py` therefore resolves Bedrock
    credentials separately, falling back to the AWS ones only if unset.
  * **The model id needs the `us.` inference-profile prefix.** A bare
    `anthropic.claude-sonnet-5` is rejected with "Invocation of model ID ...
    with on-demand throughput isn't supported. Retry your request with the ID
    or ARN of an inference profile."
  * **Corporate TLS interception breaks the SDK's HTTP client** the same way it
    breaks boto3. `app/storage/s3.py::_ca_bundle_path()` already merges the
    Windows root store into certifi's bundle for botocore; the same bundle is
    handed to httpx here. Do not swap it for `truststore` -- that was tried and
    caused `maximum recursion depth exceeded`.
"""

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import anthropic
from anthropic import AnthropicBedrockMantle, DefaultHttpxClient

from app.core.config import settings
from app.storage.s3 import _ca_bundle_path

logger = logging.getLogger(__name__)

__all__ = [
    "BedrockError",
    "LLMCall",
    "complete_json",
    "get_client",
    "last_calls",
]

# Bedrock is partner-operated and prices separately from the first-party API.
# Recorded per 1M tokens so a run can report what it cost without a lookup;
# update alongside `bedrock_model_id`.
_PRICE_PER_MTOK = {
    "us.anthropic.claude-opus-5": (5.00, 25.00),
    "us.anthropic.claude-sonnet-5": (3.00, 15.00),
    "us.anthropic.claude-haiku-4-5-20251001-v1:0": (1.00, 5.00),
}


class BedrockError(RuntimeError):
    """A model call failed, or returned something that isn't the shape asked for."""


@dataclass
class LLMCall:
    """One call, priced and timed. Plan §8's `llm_calls` row, before there is a table.

    Held in memory for now so the ingestion report and the test scripts can
    show cost per document; persisting these is a later step, and the shape is
    chosen to insert directly.
    """

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


_client: AnthropicBedrockMantle | None = None


def get_client() -> AnthropicBedrockMantle:
    """The Bedrock client, built once.

    `AnthropicBedrockMantle` rather than `AnthropicBedrock`: the Mantle client
    speaks the Messages API, so the request shape here is the same one the
    first-party API takes and nothing is written against the legacy
    `bedrock-runtime` InvokeModel path.
    """
    global _client
    if _client is None:
        _client = AnthropicBedrockMantle(
            aws_region=settings.resolved_bedrock_region,
            aws_access_key=settings.resolved_bedrock_access_key_id,
            aws_secret_key=settings.resolved_bedrock_secret_access_key,
            timeout=settings.bedrock_timeout_seconds,
            max_retries=settings.bedrock_max_retries,
            http_client=DefaultHttpxClient(verify=_ca_bundle_path()),
        )
    return _client


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

    Structured outputs rather than "reply with JSON and we'll parse it": the
    response is constrained to the schema, so a malformed reply is not a
    failure mode the callers have to handle. It is also the enforcement point
    for plan §10's contract -- the model emits *values*, never XML, never a
    cell reference, never a file path. What it may name is fixed by the enum
    the caller puts in the schema.

    Raises `BedrockError` rather than returning a sentinel: every caller in
    this project has a documented non-LLM fallback (leave the region
    `unknown`, fall back to filename + headings), and a caller that silently
    treated an error as an empty result would produce a document with regions
    quietly dropped.
    """
    model = model_id or settings.bedrock_model_id
    started = time.perf_counter()
    try:
        response = get_client().messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
    except anthropic.APIStatusError as exc:
        _record(purpose, model, prompt_version, 0, 0, started, ok=False, error=str(exc))
        raise BedrockError(
            f"{purpose}: Bedrock returned {exc.status_code} for {model} -- {exc.message}"
        ) from exc
    except anthropic.APIConnectionError as exc:
        _record(purpose, model, prompt_version, 0, 0, started, ok=False, error=str(exc))
        raise BedrockError(
            f"{purpose}: could not reach Bedrock ({exc}). On this network that is usually "
            f"the TLS bundle -- see `app/storage/s3.py::_ca_bundle_path`."
        ) from exc

    usage = response.usage
    _record(
        purpose,
        model,
        prompt_version,
        usage.input_tokens,
        usage.output_tokens,
        started,
        ok=True,
    )

    # `output_config.format` guarantees the first text block is valid JSON for
    # the schema, but a truncated response is still possible -- and it arrives
    # as a parse failure rather than an error, so it is checked by name.
    if response.stop_reason == "max_tokens":
        raise BedrockError(
            f"{purpose}: response hit max_tokens ({max_tokens}) and is truncated. "
            f"Raise max_tokens or split the batch."
        )
    text = next((block.text for block in response.content if block.type == "text"), None)
    if text is None:
        raise BedrockError(f"{purpose}: response carried no text block ({response.stop_reason})")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:  # pragma: no cover - schema-constrained
        raise BedrockError(f"{purpose}: response was not valid JSON: {exc}") from exc


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
