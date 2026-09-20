"""The AI network seam (spec 101): five role-addressed calls other modules use.

`complete` / `complete_structured` / `complete_choice` / `embed` / `stream` all
resolve a ROLE through the registry (AiDisabledError -> 404-dormant when
unconfigured) and work from the ResolvedModel value object. Any transport
error, non-2xx status, or malformed body raises AiUpstreamError (-> clean 502).
`complete_choice` + AiRole.VISION is the spec-102 storage-router contract.
"""

from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings

from . import provider, registry
from .registry import ResolvedModel
from .types import AiConfigError, AiRole, AiUpstreamError, AiWireShape

# Test seam: set to an httpx.MockTransport to exercise the full request path
# without a network (None = httpx's real transport).
transport: httpx.AsyncBaseTransport | None = None


def _completion_payload(
    resolved: ResolvedModel,
    system: str,
    user: provider.UserContent,
    *,
    max_tokens: int,
    json_schema: dict[str, Any] | None = None,
    stream: bool = False,
) -> dict[str, Any]:
    if resolved.wire_shape is AiWireShape.LOCAL:
        # Unreachable through the registry (LOCAL holds only the embeddings
        # role), kept as a hard stop for any future caller.
        raise AiConfigError("the built-in local backend only embeds")
    if resolved.wire_shape is AiWireShape.OPENAI:
        response_format = provider.json_schema_format(json_schema) if json_schema else None
        payload = provider.openai_payload(
            system,
            user,
            model=resolved.model,
            max_tokens=max_tokens,
            response_format=response_format,
            stream=stream,
        )
    else:
        payload = provider.anthropic_payload(
            system,
            user,
            model=resolved.model,
            max_tokens=max_tokens,
            tool_schema=json_schema,
            stream=stream,
        )
    # RADD-1273: every chat request — plain, structured, streamed, the probe —
    # carries the provider's reasoning preference and extra parameters.
    return provider.finish_payload(
        payload,
        resolved.wire_shape,
        reasoning=resolved.reasoning,
        request_params=resolved.request_params,
        reasoning_budget_tokens=settings.ai_reasoning_budget_tokens,
    )


async def _post(url: str, payload: dict[str, Any], headers: dict[str, str]) -> Any:
    try:
        async with httpx.AsyncClient(
            timeout=settings.ai_timeout_seconds, transport=transport
        ) as client:
            response = await client.post(url, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise AiUpstreamError(f"AI provider unreachable ({exc.__class__.__name__})") from exc
    if response.status_code >= 400:
        raise AiUpstreamError(f"AI provider returned HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise AiUpstreamError("AI provider returned a non-JSON body") from exc


async def _completion_data(
    resolved: ResolvedModel,
    system: str,
    user: provider.UserContent,
    *,
    max_tokens: int | None,
    json_schema: dict[str, Any] | None = None,
) -> Any:
    payload = _completion_payload(
        resolved,
        system,
        user,
        max_tokens=max_tokens or settings.ai_max_tokens,
        json_schema=json_schema,
    )
    url = provider.completions_url(resolved.wire_shape, resolved.base_url)
    return await _post(url, payload, provider.headers(resolved.wire_shape, resolved.api_key))


# --- the public seam ----------------------------------------------------------


async def complete(
    session: AsyncSession,
    role: AiRole,
    system: str,
    user: str,
    *,
    max_tokens: int | None = None,
) -> str:
    """One round-trip: system + user prompt -> assistant text."""
    resolved = await registry.require_role(session, role)
    data = await _completion_data(resolved, system, user, max_tokens=max_tokens)
    return provider.extract_completion_text(resolved.wire_shape, data)


async def complete_structured(
    session: AsyncSession,
    role: AiRole,
    system: str,
    user: str,
    *,
    json_schema: dict[str, Any],
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """One round-trip returning the schema-constrained answer object.

    Non-streaming by construction — structured decoding and SSE don't compose.
    """
    resolved = await registry.require_role(session, role)
    data = await _completion_data(
        resolved, system, user, max_tokens=max_tokens, json_schema=json_schema
    )
    return provider.extract_structured(resolved.wire_shape, data)


async def complete_choice(
    session: AsyncSession,
    role: AiRole,
    *,
    prompt: str,
    choices: Sequence[str],
    image_bytes: bytes | None = None,
    image_media_type: str | None = None,
) -> str:
    """Enum-constrained one-shot (optionally with an image): exactly one of
    `choices` comes back. The spec-102 storage-routing seam.

    One network call, two parse attempts: the structured answer, then a lenient
    case-insensitive match of the plain reply against the choices.
    """
    resolved = await registry.require_role(session, role)
    content = provider.user_content(resolved.wire_shape, prompt, image_bytes, image_media_type)
    system = "Answer with exactly one of the allowed values."
    data = await _completion_data(
        resolved, system, content, max_tokens=None, json_schema=provider.choice_schema(choices)
    )
    try:
        value = provider.extract_structured(resolved.wire_shape, data).get("choice")
        if isinstance(value, str) and value in choices:
            return value
    except AiUpstreamError:
        pass
    reply = provider.extract_completion_text(resolved.wire_shape, data).strip().lower()
    for choice in choices:
        if choice.lower() in reply:
            return choice
    raise AiUpstreamError("the model's reply matched none of the allowed answers")


async def embed(
    session: AsyncSession, role: AiRole, texts: Sequence[str]
) -> list[list[float]]:
    """One embedding batch -> input-ordered vectors: the /embeddings endpoint
    for OpenAI-shape providers, the built-in CPU backend for LOCAL ones (the
    registry refuses the role on Anthropic)."""
    resolved = await registry.require_role(session, role)
    if resolved.wire_shape is AiWireShape.LOCAL:
        from . import localembed

        return await localembed.embed_texts(resolved.model, texts)
    if resolved.wire_shape is not AiWireShape.OPENAI:
        raise AiConfigError("embeddings need an OpenAI-compatible or built-in provider")
    data = await _post(
        provider.embeddings_url(resolved.base_url),
        {"model": resolved.model, "input": list(texts)},
        provider.headers(resolved.wire_shape, resolved.api_key),
    )
    return provider.extract_embeddings(data)


async def probe(resolved: ResolvedModel) -> float:
    """The Test button: one max_tokens=1 completion — or, for the built-in
    LOCAL backend, one embedding (first run includes the model download) ->
    latency in ms. Raises AiUpstreamError/AiConfigError with the detail."""
    import time

    if resolved.wire_shape is AiWireShape.LOCAL:
        from . import localembed

        return await localembed.probe(resolved.model)
    started = time.monotonic()
    data = await _completion_data(resolved, "ping", "Reply with the word pong.", max_tokens=1)
    provider.extract_completion_text(resolved.wire_shape, data)
    return (time.monotonic() - started) * 1000.0


async def stream(
    session: AsyncSession,
    role: AiRole,
    system: str,
    user: str,
    *,
    max_tokens: int | None = None,
) -> AsyncIterator[str]:
    """Streamed completion: yields text deltas as they arrive.

    Cancellation propagates: when the consumer stops (client disconnect aborts
    the SSE response), the httpx stream context closes the upstream connection.
    """
    resolved = await registry.require_role(session, role)
    payload = _completion_payload(
        resolved, system, user, max_tokens=max_tokens or settings.ai_max_tokens, stream=True
    )
    url = provider.completions_url(resolved.wire_shape, resolved.base_url)
    request_headers = provider.headers(resolved.wire_shape, resolved.api_key)
    try:
        async with httpx.AsyncClient(
            timeout=settings.ai_stream_timeout_seconds, transport=transport
        ) as client:
            async with client.stream(
                "POST", url, json=payload, headers=request_headers
            ) as response:
                if response.status_code >= 400:
                    raise AiUpstreamError(
                        f"AI provider returned HTTP {response.status_code}"
                    )
                async for line in response.aiter_lines():
                    delta = provider.stream_delta(resolved.wire_shape, line)
                    if delta:
                        yield delta
    except httpx.HTTPError as exc:
        raise AiUpstreamError(f"AI provider unreachable ({exc.__class__.__name__})") from exc
