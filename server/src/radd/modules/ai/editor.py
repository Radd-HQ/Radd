"""Editor AI actions (spec 103): the menu, prompt resolution, and the SSE stream.

The contract with the frontend (Crepe's AI feature): the menu carries ids and
labels only — prompt text stays server-side; the client streams back replacement
markdown for the selection. Frames are JSON (`data: {"t": "..."}`) so newlines
survive SSE framing; failures after headers are in-band `event: error` frames.
"""

import json
import uuid
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import NotFoundError

from . import client, registry
from .schemas import EditorActionRead, EditorStreamRequest
from .types import (
    EDITOR_MAX_TOKENS,
    AiDisabledError,
    AiEntity,
    AiRole,
    AiUpstreamError,
    EditorAction,
    EditorActionKind,
)

EDITOR_SYSTEM = (
    "You are a writing assistant inside an issue tracker's markdown editor. "
    "You receive a document, optionally a selected portion, and an instruction. "
    "Apply the instruction to the SELECTION when one is given, otherwise to the "
    "whole document. Return ONLY the replacement markdown — no preamble, no "
    "commentary, and no code fence wrapping the entire reply."
)

BUILTIN_ACTIONS: dict[EditorAction, tuple[str, str]] = {
    # action -> (menu label, instruction prompt)
    EditorAction.REFINE: (
        "Refine writing",
        "Improve the clarity, grammar, and flow of the text. Keep the meaning, "
        "tone, and markdown structure. Do not add new content.",
    ),
    EditorAction.FORMAT: (
        "Format as markdown",
        "Reformat the text into clean, well-structured markdown — headings, "
        "lists, tables and code blocks where they fit. Keep the wording; only "
        "change what formatting requires.",
    ),
    EditorAction.SUMMARIZE_SELECTION: (
        "Summarize",
        "Condense the text to its essential points. Keep useful markdown "
        "structure; drop repetition and filler.",
    ),
    EditorAction.FIX_GRAMMAR: (
        "Fix grammar only",
        "Fix spelling, grammar, and punctuation mistakes with the minimal "
        "possible edits. Do not rephrase or restructure.",
    ),
}


async def list_actions(session: AsyncSession) -> list[EditorActionRead]:
    """The menu: builtins first, then enabled admin presets in position order."""
    actions = [
        EditorActionRead(id=action.value, label=label, kind=EditorActionKind.BUILTIN)
        for action, (label, _) in BUILTIN_ACTIONS.items()
    ]
    for preset in await registry.list_presets(session, enabled_only=True):
        actions.append(
            EditorActionRead(id=str(preset.id), label=preset.name, kind=EditorActionKind.PRESET)
        )
    return actions


async def resolve_instruction(session: AsyncSession, data: EditorStreamRequest) -> str:
    """The instruction text for a request: builtin prompt, preset prompt (by
    uuid), or the user's freeform instruction."""
    if data.instruction and data.instruction.strip():
        return data.instruction.strip()
    action_id = data.action_id or ""
    try:
        return BUILTIN_ACTIONS[EditorAction(action_id)][1]
    except ValueError:
        pass
    try:
        preset = await registry.get_preset(session, uuid.UUID(action_id))
    except ValueError as exc:
        raise NotFoundError(AiEntity.PRESET, action_id) from exc
    if not preset.enabled:
        raise NotFoundError(AiEntity.PRESET, action_id)
    return preset.prompt


def user_prompt(document: str, selection: str, instruction: str) -> str:
    """Pure prompt assembly (unit-tested)."""
    parts = [f"Instruction: {instruction}", "", "Document:", document]
    if selection:
        parts += ["", "Selection (replace ONLY this part):", selection]
    return "\n".join(parts)


def sse_frame(data: dict, event: str | None = None) -> str:
    """One SSE frame; JSON payloads so text chunks survive framing (pure)."""
    frame = f"data: {json.dumps(data)}\n\n"
    return f"event: {event}\n{frame}" if event else frame


async def stream_frames(
    session: AsyncSession, data: EditorStreamRequest, instruction: str
) -> AsyncIterator[str]:
    """The SSE body. Headers are already sent when this runs, so every failure
    is an in-band `event: error` frame, never an exception to the handler."""
    prompt = user_prompt(data.document, data.selection, instruction)
    try:
        async for chunk in client.stream(
            session, AiRole.CHAT, EDITOR_SYSTEM, prompt, max_tokens=EDITOR_MAX_TOKENS
        ):
            yield sse_frame({"t": chunk})
    except (AiUpstreamError, AiDisabledError) as exc:
        yield sse_frame({"detail": str(exc)}, event="error")
        return
    yield sse_frame({}, event="done")
