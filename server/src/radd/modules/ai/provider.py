"""Pure wire-shape builders (specs 46/101): payloads, headers, URLs, response
extractors, and SSE stream-line parsers for the two supported shapes.

No network in this file — `client.py` owns the calls. Everything here is a pure
function over plain data, which is the unit-test surface: OpenAI-compatible
`{base_url}/chat/completions` (covers LiteLLM/Ollama/vLLM/OpenAI) and native
Anthropic `{base_url}/v1/messages`. Structured output rides `response_format`
json_schema on the OpenAI shape and a forced tool call on Anthropic.
"""

import base64
import json
from collections.abc import Sequence
from typing import Any

from .types import ANTHROPIC_VERSION, DEFAULT_BASE_URLS, AiUpstreamError, AiWireShape

# The forced-tool name carrying structured output on the Anthropic shape.
STRUCTURED_TOOL_NAME = "answer"

# SSE line prefix / sentinel (both shapes emit `data: {...}` frames).
_SSE_DATA_PREFIX = "data:"
_OPENAI_DONE = "[DONE]"

# User-message content: a plain string, or a content-part list (vision).
UserContent = str | list[dict[str, Any]]


# --- payloads -----------------------------------------------------------------


def openai_payload(
    system: str,
    user: UserContent,
    *,
    model: str,
    max_tokens: int,
    response_format: dict[str, Any] | None = None,
    stream: bool = False,
) -> dict[str, Any]:
    """OpenAI chat.completions body — the system prompt rides as the leading message."""
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if response_format is not None:
        payload["response_format"] = response_format
    if stream:
        payload["stream"] = True
    return payload


def anthropic_payload(
    system: str,
    user: UserContent,
    *,
    model: str,
    max_tokens: int,
    tool_schema: dict[str, Any] | None = None,
    stream: bool = False,
) -> dict[str, Any]:
    """Anthropic /v1/messages body — top-level `system`; `max_tokens` is REQUIRED.

    `tool_schema` forces one tool call whose input IS the structured answer.
    """
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    if tool_schema is not None:
        payload["tools"] = [{"name": STRUCTURED_TOOL_NAME, "input_schema": tool_schema}]
        payload["tool_choice"] = {"type": "tool", "name": STRUCTURED_TOOL_NAME}
    if stream:
        payload["stream"] = True
    return payload


def json_schema_format(
    schema: dict[str, Any], *, name: str = STRUCTURED_TOOL_NAME
) -> dict[str, Any]:
    """OpenAI `response_format` wrapper for one JSON schema (strict decoding)."""
    return {
        "type": "json_schema",
        "json_schema": {"name": name, "schema": schema, "strict": True},
    }


def choice_schema(choices: Sequence[str]) -> dict[str, Any]:
    """Schema constraining the answer to exactly one of `choices` (the spec-102
    storage router's contract: the model cannot invent an unmapped answer)."""
    return {
        "type": "object",
        "properties": {"choice": {"type": "string", "enum": list(choices)}},
        "required": ["choice"],
        "additionalProperties": False,
    }


# --- vision content parts -----------------------------------------------------


def openai_user_content(text: str, image_bytes: bytes, media_type: str) -> list[dict[str, Any]]:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return [
        {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{encoded}"}},
        {"type": "text", "text": text},
    ]


def anthropic_user_content(text: str, image_bytes: bytes, media_type: str) -> list[dict[str, Any]]:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": encoded},
        },
        {"type": "text", "text": text},
    ]


def user_content(
    shape: AiWireShape, text: str, image_bytes: bytes | None, media_type: str | None
) -> UserContent:
    if image_bytes is None:
        return text
    builder = openai_user_content if shape is AiWireShape.OPENAI else anthropic_user_content
    return builder(text, image_bytes, media_type or "image/png")


# --- headers / URLs -----------------------------------------------------------


def openai_headers(api_key: str) -> dict[str, str]:
    # Keyless self-hosted endpoints (vLLM/Ollama) get NO auth header — an empty
    # "Bearer " value is an illegal header h11 refuses to send (LocalProtocolError).
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def anthropic_headers(api_key: str) -> dict[str, str]:
    headers = {"anthropic-version": ANTHROPIC_VERSION}
    if api_key:
        headers["x-api-key"] = api_key
    return headers


def headers(shape: AiWireShape, api_key: str) -> dict[str, str]:
    return openai_headers(api_key) if shape is AiWireShape.OPENAI else anthropic_headers(api_key)


def completions_url(provider: AiWireShape, base_url: str) -> str:
    """Endpoint URL for one completion ('' base_url = the shape's default)."""
    root = (base_url or DEFAULT_BASE_URLS[provider]).rstrip("/")
    suffix = "/chat/completions" if provider is AiWireShape.OPENAI else "/v1/messages"
    return root + suffix


def embeddings_url(base_url: str) -> str:
    """OpenAI-shape /embeddings (base URLs include /v1 by the completions convention)."""
    return (base_url or DEFAULT_BASE_URLS[AiWireShape.OPENAI]).rstrip("/") + "/embeddings"


# --- response extractors ------------------------------------------------------


def extract_completion_text(provider: AiWireShape, data: Any) -> str:
    """Assistant text out of a success body; AiUpstreamError on any shape surprise."""
    try:
        if provider is AiWireShape.OPENAI:
            return data["choices"][0]["message"]["content"] or ""
        blocks = data["content"]
        if not isinstance(blocks, list):
            raise TypeError("content is not a list")
        return "".join(block.get("text", "") for block in blocks if isinstance(block, dict))
    except (KeyError, IndexError, TypeError) as exc:
        raise AiUpstreamError(f"unexpected {provider} response shape") from exc


def extract_structured(shape: AiWireShape, data: Any) -> dict[str, Any]:
    """The structured answer object: parsed message content (OpenAI) or the
    forced tool call's input (Anthropic). AiUpstreamError when absent/unparseable."""
    try:
        if shape is AiWireShape.OPENAI:
            value = json.loads(data["choices"][0]["message"]["content"])
            if not isinstance(value, dict):
                raise TypeError("structured reply is not an object")
            return value
        for block in data["content"]:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                value = block.get("input")
                if isinstance(value, dict):
                    return value
        raise KeyError("no tool_use block")
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise AiUpstreamError(f"no structured answer in {shape} response") from exc


def extract_embeddings(data: Any) -> list[list[float]]:
    """Vectors out of an /embeddings body, input-ordered via each row's index."""
    try:
        rows = sorted(data["data"], key=lambda row: row["index"])
        return [list(map(float, row["embedding"])) for row in rows]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise AiUpstreamError("unexpected embeddings response shape") from exc


# --- SSE stream-line parsers --------------------------------------------------


def _sse_json(line: str) -> Any | None:
    """The JSON payload of one `data: {...}` SSE line, else None (blank lines,
    `event:` lines, the [DONE] sentinel, unparseable frames)."""
    stripped = line.strip()
    if not stripped.startswith(_SSE_DATA_PREFIX):
        return None
    body = stripped[len(_SSE_DATA_PREFIX) :].strip()
    if not body or body == _OPENAI_DONE:
        return None
    try:
        return json.loads(body)
    except ValueError:
        return None


def openai_stream_delta(line: str) -> str | None:
    """Text delta in one OpenAI-shape SSE line, else None."""
    data = _sse_json(line)
    if not isinstance(data, dict):
        return None
    try:
        delta = data["choices"][0].get("delta", {})
    except (KeyError, IndexError, TypeError):
        return None
    text = delta.get("content") if isinstance(delta, dict) else None
    return text if isinstance(text, str) and text else None


def anthropic_stream_delta(line: str) -> str | None:
    """Text delta in one Anthropic-shape SSE line (content_block_delta), else None."""
    data = _sse_json(line)
    if not isinstance(data, dict) or data.get("type") != "content_block_delta":
        return None
    delta = data.get("delta")
    if not isinstance(delta, dict) or delta.get("type") != "text_delta":
        return None
    text = delta.get("text")
    return text if isinstance(text, str) and text else None


def stream_delta(shape: AiWireShape, line: str) -> str | None:
    parser = openai_stream_delta if shape is AiWireShape.OPENAI else anthropic_stream_delta
    return parser(line)
