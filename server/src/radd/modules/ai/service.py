"""AI feature flows (spec 46): summarize, similar (semantic-first with an FTS
fallback + optional LLM rerank), and NL->SLQ with server-side compile
validation + one retry.

Every path enforces the caller's ordinary RBAC (item.read via the items/search
services). Nothing is stored — responses go straight back to the caller. The
JSON extractors, rerank merge, and retry decision are pure and unit-tested.
"""

import json
import re
import uuid
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth import authz
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User
from radd.modules.comments import service as comments_service
from radd.modules.fields import service as fields_service
from radd.modules.fields.models import FieldDefinition
from radd.modules.items import service as items_service, slq
from radd.modules.items.history import item_history
from radd.modules.items.schemas import HistoryEntry
from radd.modules.search import service as search_service
from radd.modules.search.service import SearchHit
from radd.modules.settings import service as settings_service
from radd.modules.settings.types import SettingKey

from . import client, features, nlrepair, prompts, registry
from .editor import sse_frame
from .types import (
    FTS_MATCH_REASON,
    NL_MAX_ATTEMPTS,
    SIMILAR_CANDIDATE_POOL,
    SUMMARY_COMMENTS_BUDGET_CHARS,
    SUMMARY_HISTORY_BUDGET_CHARS,
    SUMMARY_MAX_COMMENT_CHARS,
    SUMMARY_MAX_DESCRIPTION_CHARS,
    SUMMARY_MAX_WORKLOG_NOTE_CHARS,
    SUMMARY_WORKLOG_BUDGET_CHARS,
    AiDisabledError,
    AiFeature,
    AiInvalidQueryError,
    AiRole,
    AiStatus,
    AiUpstreamError,
    NlOutcome,
    NlQueryResponse,
    SlqDialect,
    SimilarCandidate,
    SimilarResponse,
    SummarizeResponse,
)


async def status(session: AsyncSession) -> AiStatus:
    """{enabled, provider, model, features} — what the frontend gates on.

    `enabled` = the chat role resolves (back-compat: pre-101 frontends read only
    this); `provider` stays the wire shape string it always was.
    """
    chat = await registry.resolve_role(session, AiRole.CHAT)
    feature_map = {
        feature.value: await features.feature_enabled(session, feature)
        for feature in AiFeature
    }
    stream_on = bool(await settings_service.resolve(session, SettingKey.AI_STREAM_RESPONSES))
    if chat is None:
        return AiStatus(enabled=False, features=feature_map, stream_responses=stream_on)
    return AiStatus(
        enabled=True,
        provider=str(chat.wire_shape),
        model=chat.model,
        features=feature_map,
        stream_responses=stream_on,
    )


# --- summarize ---


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
        description=read.description[:SUMMARY_MAX_DESCRIPTION_CHARS],
        comments=take_recent(
            [
                (comment.author.name, comment.body[:SUMMARY_MAX_COMMENT_CHARS])
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


async def summarize_item(
    session: AsyncSession, item_id: uuid.UUID, actor: User
) -> SummarizeResponse:
    """Hand-off summary in one go (the Stream-AI-responses setting off)."""
    user_prompt = await summarize_prompt(session, item_id, actor)
    summary = await client.complete(session, AiRole.CHAT, prompts.SUMMARIZE_SYSTEM, user_prompt)
    return SummarizeResponse(summary=summary.strip())


def summarize_stream_frames(session: AsyncSession, user_prompt: str) -> AsyncIterator[str]:
    """SSE body for the streaming summarize (the editor's frame contract)."""
    return _chat_stream_frames(session, prompts.SUMMARIZE_SYSTEM, user_prompt)


async def _chat_stream_frames(
    session: AsyncSession, system: str, user_prompt: str
) -> AsyncIterator[str]:
    """One chat completion as SSE frames — `data: {"t": …}` per token batch,
    then `event: done`; provider failures are in-band `event: error` frames
    (headers are already sent when the body generator runs)."""
    try:
        async for chunk in client.stream(session, AiRole.CHAT, system, user_prompt):
            yield sse_frame({"t": chunk})
    except (AiUpstreamError, AiDisabledError) as exc:
        yield sse_frame({"detail": str(exc)}, event="error")
        return
    yield sse_frame({}, event="done")


# --- similar (semantic-first; degrades, never disappears) ---


def fts_candidates(hits: Sequence[tuple[SearchHit, float]]) -> list[SimilarCandidate]:
    """FTS ranks -> 0..1 scores by dividing by the top rank (pure)."""
    top = max((rank for _, rank in hits), default=0.0)
    return [
        SimilarCandidate(
            item_key=hit.key,
            title=hit.title,
            score=round(rank / top, 3) if top > 0 else 0.0,
            reason=FTS_MATCH_REASON,
        )
        for hit, rank in hits
    ]


def extract_json_array(text: str) -> list | None:
    """First JSON array in an LLM reply, tolerant of prose/code fences (pure).

    Tries every '[' as a start offset until one parses; None when nothing does.
    """
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\[", text):
        try:
            value, _ = decoder.raw_decode(text[match.start() :])
        except ValueError:
            continue
        if isinstance(value, list):
            return value
    return None


def extract_json_object(text: str) -> dict | None:
    """First JSON object in an LLM reply, same leniency as extract_json_array (pure)."""
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text[match.start() :])
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


def parse_stream_objects(buffer: str, offset: int) -> tuple[list[dict], int]:
    """Complete top-level JSON objects in `buffer[offset:]` plus the resume
    offset (pure). The similar-reasons stream feeds the GROWING reply through
    this and emits one SSE event per completed candidate object — an object
    split across chunks stays unconsumed until its closing brace arrives, and
    a brace inside an unterminated string keeps the whole object pending."""
    decoder = json.JSONDecoder()
    found: list[dict] = []
    cursor = offset
    while True:
        start = buffer.find("{", cursor)
        if start == -1:
            return found, len(buffer)  # nothing pending — resume at the end
        try:
            value, consumed = decoder.raw_decode(buffer[start:])
        except ValueError:
            return found, start  # incomplete — retry from this object next chunk
        if isinstance(value, dict):
            found.append(value)
        cursor = start + consumed


def clean_reason_entry(entry: dict, allowed: set[str], seen: set[str]) -> dict | None:
    """One streamed model entry -> the {key, score, reason} SSE payload, or
    None for unusable entries (pure; mirrors apply_rerank's tolerance: unknown
    or duplicate keys and non-numeric scores are dropped). Mutates `seen`."""
    key = entry.get("key") or entry.get("item_key")
    score = entry.get("score")
    if not isinstance(key, str) or key not in allowed or key in seen:
        return None
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        return None
    seen.add(key)
    reason = entry.get("reason")
    return {
        "key": key,
        "score": round(min(max(float(score), 0.0), 1.0), 3),
        "reason": reason if isinstance(reason, str) and reason else None,
    }


def apply_rerank(
    candidates: Sequence[SimilarCandidate], parsed: Sequence[Any]
) -> list[SimilarCandidate] | None:
    """Merge the LLM's [{key, score, reason}] onto the FTS candidates (pure).

    Unknown/duplicate keys and malformed entries are ignored; candidates the
    model omitted are filtered out (its filter pass); result ordered by score
    descending. None when nothing usable survives -> caller keeps FTS order.
    """
    by_key = {candidate.item_key: candidate for candidate in candidates}
    merged: list[SimilarCandidate] = []
    seen: set[str] = set()
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        key = entry.get("key") or entry.get("item_key")
        score = entry.get("score")
        if not isinstance(key, str) or key not in by_key or key in seen:
            continue
        if not isinstance(score, (int, float)) or isinstance(score, bool):
            continue
        seen.add(key)
        reason = entry.get("reason")
        merged.append(
            by_key[key].model_copy(
                update={
                    "score": round(min(max(float(score), 0.0), 1.0), 3),
                    "reason": reason if isinstance(reason, str) and reason else by_key[key].reason,
                }
            )
        )
    if not merged:
        return None
    merged.sort(key=lambda candidate: candidate.score, reverse=True)
    return merged


SEMANTIC_MATCH_REASON = "semantic match"


async def _semantic_pool(
    session: AsyncSession,
    text_seed: str,
    actor: User,
    *,
    item_id: uuid.UUID | None = None,
    exclude_item_id: uuid.UUID | None = None,
) -> list[SimilarCandidate]:
    """Vector-NN candidates (spec 103), [] on any failure or when semantic
    search is off — the FTS pool always stands on its own. Seeded by an item's
    stored vector when `item_id` is given (its neighbors exclude it), else by
    embedding `text_seed` on the fly (read-mode AI menu on comments)."""
    try:
        from radd.modules.ai.embeddings import candidates as semantic
    except ImportError:
        return []
    try:
        if not await semantic.semantic_enabled(session):
            return []
        readable = await search_service.readable_project_ids(session, actor)
        if not readable:
            return []
        if item_id is not None:
            neighbors = await semantic.item_neighbors(
                session,
                item_id,
                text_seed,
                project_ids=list(readable),
                limit=SIMILAR_CANDIDATE_POOL,
            )
        else:
            neighbors = await semantic.item_candidates(
                session,
                text_seed,
                project_ids=list(readable),
                exclude_item_id=exclude_item_id,
                limit=SIMILAR_CANDIDATE_POOL,
            )
        if not neighbors:
            return []
        rows = await search_service.rows_for_embedding(
            session, item_ids=[neighbor_id for neighbor_id, _ in neighbors]
        )
        titles = {row.item_id: (row.key, row.title) for row in rows}
        pool: list[SimilarCandidate] = []
        for neighbor_id, distance in neighbors:
            named = titles.get(neighbor_id)
            if named is None:
                continue
            pool.append(
                SimilarCandidate(
                    item_key=named[0],
                    title=named[1],
                    score=round(max(0.0, 1.0 - distance), 3),
                    reason=SEMANTIC_MATCH_REASON,
                )
            )
        return pool
    except Exception:  # noqa: BLE001 — similar must never 500 over the vector half
        return []


async def similar_items(
    session: AsyncSession, item_id: uuid.UUID, actor: User, *, limit: int
) -> SimilarResponse:
    """Candidate duplicates for an item: SEMANTIC-FIRST — the
    stored vector's neighbors ARE the pool when the embedding half is up; the
    OR-ed FTS pool runs only as the fallback (one shared common token was
    enough to surface an unrelated issue as a top "text match", and its
    top-rank-normalized score always read 100%). LLM-rescored when the rerank
    feature is enabled. Degrades pool by pool — FTS-only without pgvector,
    unreranked without a chat model."""
    read = await items_service.get_item(session, item_id, actor)  # enforces item.read
    ai_on = await features.feature_enabled(session, AiFeature.SIMILAR_RERANK)
    stream_on = bool(await settings_service.resolve(session, SettingKey.AI_STREAM_RESPONSES))
    text_seed = f"{read.title}\n{read.description}"
    snippets: dict[str, str] = {}
    candidates = await _semantic_pool(session, text_seed, actor, item_id=item_id)
    if not candidates:
        hits = await search_service.similar_to_text(
            session,
            text_seed,
            user=actor,
            exclude_item_id=item_id,
            limit=max(limit, SIMILAR_CANDIDATE_POOL) if ai_on else limit,
        )
        candidates = fts_candidates(hits)
        snippets = {hit.key: hit.snippet or "" for hit, _ in hits}
    if not ai_on or not candidates:
        return SimilarResponse(candidates=candidates[:limit], reranked=False)
    if stream_on:
        # Candidates go back NOW; the client follows up on the
        # /similar/reasons stream for scores + reasoning. reranked=False is
        # honest — this payload is the raw pool order.
        return SimilarResponse(candidates=candidates[:limit], reranked=False)

    reply = await client.complete(
        session,
        AiRole.CHAT,
        prompts.SIMILAR_SYSTEM,
        prompts.similar_user_prompt(
            key=read.key,
            title=read.title,
            description=read.description[:SUMMARY_MAX_DESCRIPTION_CHARS],
            # Semantic candidates carry no FTS headline — the model judges
            # those on title alone.
            candidates=[
                (candidate.item_key, candidate.title, snippets.get(candidate.item_key, ""))
                for candidate in candidates
            ],
        ),
    )
    parsed = extract_json_array(reply)
    if parsed is None:  # unparseable reply -> degrade to FTS order, flagged
        return SimilarResponse(candidates=candidates[:limit], reranked=False)
    if not parsed:  # an empty array is a real answer: nothing looks like a dup
        return SimilarResponse(candidates=[], reranked=True)
    reranked = apply_rerank(candidates, parsed)
    if reranked is None:
        return SimilarResponse(candidates=candidates[:limit], reranked=False)
    return SimilarResponse(candidates=reranked[:limit], reranked=True)


async def similar_to_seed(
    session: AsyncSession,
    text: str,
    actor: User,
    *,
    exclude_item_id: uuid.UUID | None,
    limit: int,
) -> SimilarResponse:
    """Candidate issues for a TEXT seed (read-mode AI menu on comments, the
    form assist panel): the same SEMANTIC-FIRST retrieval as `similar_items` —
    vector neighbors when the embedding half is up, the OR-ed FTS pool only as
    the fallback. Never LLM-reranked — the rerank prompt compares against a
    source issue, and a text seed has none."""
    candidates = await _semantic_pool(
        session, text, actor, exclude_item_id=exclude_item_id
    )
    if not candidates:
        hits = await search_service.similar_to_text(
            session, text, user=actor, exclude_item_id=exclude_item_id, limit=limit
        )
        candidates = fts_candidates(hits)
    return SimilarResponse(candidates=candidates[:limit], reranked=False)


async def similar_reasons_prompt(
    session: AsyncSession, item_id: uuid.UUID, actor: User, keys: Sequence[str]
) -> str | None:
    """Gate + rerank prompt for the reasons STREAM (run before the response
    starts, so a dormant feature 404s as ordinary JSON). The client sends the
    keys it is displaying — pools aren't perfectly deterministic between two
    calls — and titles are re-resolved under the caller's RBAC. None when no
    requested key survives: the stream is just `done`."""
    await features.require_feature(session, AiFeature.SIMILAR_RERANK)
    read = await items_service.get_item(session, item_id, actor)
    titled = await search_service.titles_for_keys(session, list(keys), user=actor)
    if not titled:
        return None
    return prompts.similar_user_prompt(
        key=read.key,
        title=read.title,
        description=read.description[:SUMMARY_MAX_DESCRIPTION_CHARS],
        candidates=[(key, title, "") for key, title in titled],
    )


async def similar_reason_frames(
    session: AsyncSession, user_prompt: str, keys: Sequence[str]
) -> AsyncIterator[str]:
    """SSE body: one `data: {"key", "score", "reason"}` frame per candidate as
    the model's JSON array streams in, then `event: done` — the panel hydrates
    reasons row by row instead of blocking the candidate list on the LLM."""
    allowed = set(keys)
    seen: set[str] = set()
    buffer = ""
    offset = 0
    try:
        async for chunk in client.stream(
            session, AiRole.CHAT, prompts.SIMILAR_SYSTEM, user_prompt
        ):
            buffer += chunk
            parsed, offset = parse_stream_objects(buffer, offset)
            for entry in parsed:
                payload = clean_reason_entry(entry, allowed, seen)
                if payload is not None:
                    yield sse_frame(payload)
    except (AiUpstreamError, AiDisabledError) as exc:
        yield sse_frame({"detail": str(exc)}, event="error")
        return
    yield sse_frame({}, event="done")


async def done_only_frames() -> AsyncIterator[str]:
    """The empty stream (no readable candidates): headers, `done`, nothing else."""
    yield sse_frame({}, event="done")


# --- NL -> SLQ ---

_NO_QUERY_ERROR = "the reply contained no JSON object with a non-empty 'slq' string"


def decide(attempt: int, error: str | None) -> NlOutcome:
    """Validation-retry decision (pure): valid -> accept; first failure -> retry
    with the error in-prompt; failure on the last allowed attempt -> reject (422)."""
    if error is None:
        return NlOutcome.ACCEPT
    return NlOutcome.RETRY if attempt < NL_MAX_ATTEMPTS - 1 else NlOutcome.REJECT


async def _compile_error(
    session: AsyncSession,
    slq_text: str,
    *,
    definitions_by_key: dict[str, FieldDefinition],
    actor_id: uuid.UUID,
    dialect: SlqDialect = SlqDialect.ITEMS,
) -> str | None:
    """Parse + compile the generated query against the target DIALECT's
    compiler; the SlqError message when invalid, None when it compiles."""
    try:
        if dialect is SlqDialect.WORKLOG:
            # Deferred: timelogging is optional; without it the dialect is too.
            try:
                from radd.modules.timelogging.slq import compiler as worklog_compiler
            except ImportError:
                return "the timesheet query surface is not available on this instance"
            await worklog_compiler.compile_worklog_query(
                session, slq.parse(slq_text), current_user_id=actor_id
            )
        else:
            await slq.compile_query(
                session,
                slq.parse(slq_text),
                definitions_by_key=definitions_by_key,
                current_user_id=actor_id,
            )
    except slq.SlqError as exc:
        return str(exc)
    return None


async def nl_to_slq(
    session: AsyncSession,
    *,
    question: str,
    actor: User,
    dialect: SlqDialect = SlqDialect.ITEMS,
) -> NlQueryResponse:
    """Natural language -> SLQ. The system prompt embeds the frozen grammar plus
    the field registry; the produced query is VALIDATED by compiling it
    server-side (invalid -> one retry with the error in-prompt, then 422).
    `dialect` targets the surface the caller filters (spec 98: the timesheet's
    rows are worklogs — item fields ride `issue.` there)."""
    await features.require_feature(session, AiFeature.NL_SLQ)
    await authz.require(session, actor, Permission.ITEM_READ)
    definitions = await fields_service.list_fields(session)
    # Small live value sets ride in the prompt (types/categories are a handful;
    # users/labels are not — those resolve via the repair pass instead).
    from radd.modules.items.slq.suggest_values import SuggestScope, value_candidates

    issue_types = [
        c.value for c in await value_candidates(session, SuggestScope(), "type", "", {})
    ]
    work_categories = (
        [c.value for c in await nlrepair.category_candidates(session)]
        if dialect is SlqDialect.WORKLOG
        else []
    )
    system = prompts.nl_system_prompt(
        definitions,
        dialect=dialect.value,
        issue_types=issue_types,
        work_categories=work_categories,
    )
    definitions_by_key: dict[str, FieldDefinition] = {}
    for definition in definitions:
        definitions_by_key.setdefault(definition.key, definition)

    from datetime import date as _date

    user_prompt = prompts.nl_user_prompt(question, today=_date.today().isoformat())
    last_slq, last_error = "", _NO_QUERY_ERROR
    for attempt in range(NL_MAX_ATTEMPTS):
        reply = await client.complete(session, AiRole.CHAT, system, user_prompt)
        parsed = extract_json_object(reply) or {}
        candidate = parsed.get("slq")
        explanation = parsed.get("explanation")
        repair_notes: list[str] = []
        if isinstance(candidate, str) and candidate.strip():
            candidate = candidate.strip()
            # Value repair (spec 103 addendum): resolve entity values against the
            # live records BEFORE validation — for most fields an unknown value
            # would otherwise compile into a silent zero-row query ("jimmy" vs
            # the account "Jimmy Lee Barlow").
            try:
                parsed_query = slq.parse(candidate)
            except slq.SlqError as exc:
                error = str(exc)
            else:
                repaired, repairs = await nlrepair.repair_query(
                    session,
                    parsed_query,
                    definitions_by_key=definitions_by_key,
                    dialect=dialect.value,
                )
                if repairs:
                    candidate = slq.render(repaired)
                    repair_notes = [repair.note() for repair in repairs]
                error = await _compile_error(
                    session,
                    candidate,
                    definitions_by_key=definitions_by_key,
                    actor_id=actor.id,
                    dialect=dialect,
                )
        else:
            candidate, error = "", _NO_QUERY_ERROR
        outcome = decide(attempt, error)
        if outcome is NlOutcome.ACCEPT:
            explanation_text = explanation if isinstance(explanation, str) else ""
            if repair_notes:
                joined = "; ".join(repair_notes)
                suffix = f"{joined[0].upper()}{joined[1:]}."
                explanation_text = f"{explanation_text} {suffix}".strip()
            return NlQueryResponse(slq=candidate, explanation=explanation_text)
        last_slq, last_error = candidate, error or _NO_QUERY_ERROR
        if outcome is NlOutcome.RETRY:
            user_prompt = prompts.nl_retry_prompt(question, last_slq, last_error)
    raise AiInvalidQueryError(last_slq, last_error)
