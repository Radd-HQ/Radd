"""Summarize: the digest prompt + one-shot/streaming completions, split out of
`service.py` (RADD-902) along its own "summarize" marker.

Shares almost nothing with `similar.py`/`nlslq.py` — that's why the split was
marker-separated rather than by size. `service.py` re-exports everything here
under its own name.
"""

import uuid
from collections.abc import AsyncIterator, Callable, Sequence
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.attachments.types import AttachmentParentType
from radd.modules.auth.models import User
from radd.modules.comments import service as comments_service
from radd.modules.items import service as items_service
from radd.modules.items.history import item_history
from radd.modules.items.schemas import HistoryEntry

from . import client, features, images, prompts
from .images import ImagePart
from .prose import prose
from .editor import sse_frame
from .types import (
    SUMMARY_COMMENTS_BUDGET_CHARS,
    SUMMARY_HISTORY_BUDGET_CHARS,
    SUMMARY_MAX_COMMENT_CHARS,
    SUMMARY_MAX_DESCRIPTION_CHARS,
    SUMMARY_MAX_WORKLOG_NOTE_CHARS,
    SUMMARY_WORKLOG_BUDGET_CHARS,
    AiDisabledError,
    AiFeature,
    AiRole,
    AiUpstreamError,
    SummarizeResponse,
)


def history_line(entry: HistoryEntry) -> str:
    """One compact digest line for the summarize prompt (pure)."""
    actor = entry.actor.name if entry.actor else "someone"
    day = entry.at.date().isoformat()
    if entry.changes:
        parts = []
        for change in entry.changes:
            field = change.get("field", "field")
            if "from" in change or "to" in change:
                name = change.get("name", field)
                parts.append(f"{name}: {change.get('from')} -> {change.get('to')}")
            else:
                parts.append(f"{field} changed")
        return f"{day} {actor}: " + "; ".join(parts)
    return f"{day} {actor}: {entry.type}"


T = TypeVar("T")


def take_recent(entries: Sequence[T], budget_chars: int, size: Callable[[T], int]) -> list[T]:
    """The newest entries that fit a char budget, original order kept (pure).

    Walks from the end keeping whole entries; the newest one is always kept
    even when it alone overflows, so one huge comment can't blank a section.
    """
    taken: list[T] = []
    used = 0
    for entry in reversed(entries):
        used += size(entry)
        if taken and used > budget_chars:
            break
        taken.append(entry)
        if used > budget_chars:
            break
    return list(reversed(taken))


async def _worklog_digest(
    session: AsyncSession, item_id: uuid.UUID, project_id: uuid.UUID
) -> list[str]:
    """Time-tracking lines for the summarize prompt: the logged/estimate totals,
    a per-person split, then the newest entries under a char budget.

    [] whenever the timelogging module is absent OR the project has it off —
    the prompt section simply never appears (deferred feature-detected import,
    the deflect precedent).
    """
    try:
        from radd.modules.timelogging import enablement
        from radd.modules.timelogging import service as timelog_service
    except ImportError:
        return []
    try:
        if not await enablement.is_enabled(session, project_id):
            return []
        from radd.modules.projects import service as projects_service

        project = await projects_service.get_project(session, project_id)
        summary = await timelog_service.item_summary(session, item_id, project)
        if not summary.entries:
            return []
        header = f"Total logged: {summary.logged}"
        if summary.original_estimate:
            header += f" (estimate {summary.original_estimate}"
            header += f", remaining {summary.remaining})" if summary.remaining else ")"
        lines = [header]
        by_person: dict[str, int] = {}
        for entry in summary.entries:
            by_person[entry.author.name] = (
                by_person.get(entry.author.name, 0) + entry.time_spent_seconds
            )
        if len(by_person) > 1:
            split = "; ".join(
                f"{name} {seconds / 3600:.1f}h"
                for name, seconds in sorted(by_person.items(), key=lambda kv: -kv[1])
            )
            lines.append(f"By person: {split}")
        entry_lines = [
            f"{entry.worked_on.isoformat()} {entry.author.name}"
            + (f" ({entry.category.name})" if entry.category else "")
            + f" {entry.time_spent}"
            + (f": {entry.note[:SUMMARY_MAX_WORKLOG_NOTE_CHARS]}" if entry.note else "")
            for entry in summary.entries
        ]
        # worklogs_for_item orders newest-first; flip to oldest-first so the
        # budgeted suffix reads chronologically like the other sections.
        entry_lines.reverse()
        lines.extend(take_recent(entry_lines, SUMMARY_WORKLOG_BUDGET_CHARS, len))
        return lines
    except Exception:  # noqa: BLE001 — summarize must not 500 over its time digest
        return []


async def summarize_prompt(session: AsyncSession, item_id: uuid.UUID, actor: User) -> str:
    """Gate + digest prompt, shared by the one-shot and STREAMING summarize.
    The streaming router calls this BEFORE the response starts, so a dormant
    feature or unreadable item fails as ordinary JSON (404/403), never in-band.

    item.read enforced by the items/comments/history reads themselves, so the
    digest only ever contains what the caller could see anyway. Not stored.
    """
    await features.require_feature(session, AiFeature.SUMMARIZE)
    read = await items_service.get_item(session, item_id, actor)
    comments = await comments_service.list_comments(session, item_id, actor)
    history = await item_history(session, item_id, actor)
    user_prompt = prompts.summarize_user_prompt(
        key=read.key,
        title=read.title,
        kind=str(read.kind),
        state=read.state.name,
        priority=str(read.priority),
        assignee=read.assignee.name if read.assignee else None,
        labels=read.labels,
        # RADD-1232: prose only — image references, data URIs and bare
        # addresses are budget spent on strings the model can only guess at.
        description=prose(read.description)[:SUMMARY_MAX_DESCRIPTION_CHARS],
        comments=take_recent(
            [
                (comment.author.name, prose(comment.body)[:SUMMARY_MAX_COMMENT_CHARS])
                for comment in comments
            ],
            SUMMARY_COMMENTS_BUDGET_CHARS,
            lambda pair: len(pair[0]) + len(pair[1]),
        ),
        history=take_recent(
            [history_line(entry) for entry in history.entries],
            SUMMARY_HISTORY_BUDGET_CHARS,
            len,
        ),
        worklogs=await _worklog_digest(session, item_id, read.project_id),
    )
    return user_prompt


async def summarize_images(
    session: AsyncSession, item_id: uuid.UUID, actor: User
) -> list[ImagePart]:
    """RADD-1275: the item's image attachments this reader may show a vision
    model — empty, without touching storage, when no vision role is assigned."""
    return await images.entity_images(session, actor, AttachmentParentType.ITEM.value, item_id)


def with_images(user_prompt: str, pictures: Sequence[ImagePart]) -> tuple[AiRole, str]:
    """Which role answers and what the text part says: the vision role and a
    filename roster when pictures ride along, the chat role and the prompt
    untouched when none do (pure)."""
    if not pictures:
        return AiRole.CHAT, user_prompt
    return AiRole.VISION, f"{user_prompt}\n\n{images.images_note(pictures)}"


async def summarize_item(
    session: AsyncSession, item_id: uuid.UUID, actor: User
) -> SummarizeResponse:
    """Hand-off summary in one go (the Stream-AI-responses setting off)."""
    user_prompt = await summarize_prompt(session, item_id, actor)
    pictures = await summarize_images(session, item_id, actor)
    role, text = with_images(user_prompt, pictures)
    summary = await client.complete(
        session, role, prompts.SUMMARIZE_SYSTEM, text, images=_wire(pictures)
    )
    return SummarizeResponse(summary=summary.strip())


def summarize_stream_frames(
    session: AsyncSession, user_prompt: str, pictures: Sequence[ImagePart] = ()
) -> AsyncIterator[str]:
    """SSE body for the streaming summarize (the editor's frame contract)."""
    role, text = with_images(user_prompt, pictures)
    return _chat_stream_frames(session, prompts.SUMMARIZE_SYSTEM, text, role=role, pictures=pictures)


def _wire(pictures: Sequence[ImagePart]) -> list[tuple[bytes, str]]:
    return [(picture.data, picture.media_type) for picture in pictures]


async def _chat_stream_frames(
    session: AsyncSession,
    system: str,
    user_prompt: str,
    *,
    role: AiRole = AiRole.CHAT,
    pictures: Sequence[ImagePart] = (),
) -> AsyncIterator[str]:
    """One chat completion as SSE frames — `data: {"t": …}` per token batch,
    then `event: done`; provider failures are in-band `event: error` frames
    (headers are already sent when the body generator runs)."""
    try:
        async for chunk in client.stream(
            session, role, system, user_prompt, images=_wire(pictures)
        ):
            yield sse_frame({"t": chunk})
    except (AiUpstreamError, AiDisabledError) as exc:
        yield sse_frame({"detail": str(exc)}, event="error")
        return
    yield sse_frame({}, event="done")
