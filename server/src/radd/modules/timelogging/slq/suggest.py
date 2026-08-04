"""Autocomplete for the worklog dialect — including the delegated `issue.` half.

The delegation is the same trick the compiler uses, applied to completion: when
the token under the cursor starts with `issue.`, we hand the whole query to the
ITEM suggester with that prefix spliced out, and shift the returned offset back.
So `issue.assi|` completes to `issue.assignee` using the item dialect's own
field list, value resolvers and ranking — this module never restates them, and
anything the item dialect learns later (a new custom field, a plugin field) is
completable here the day it exists.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth import authz
from radd.modules.auth.models import User
from radd.modules.items.slq.suggest import Suggestion, SuggestResponse, suggestions_for
from radd.modules.items.slq.suggest_context import SuggestContext, detect
from radd.modules.items.slq.suggest_values import SuggestScope
from radd.modules.projects.models import Project

from ..models import WorkCategory
from .catalog import FIELD_LABELS, ISSUE_PREFIX, WORKLOG_OPS, WorklogField

#: Offered as a field so the delegated half is discoverable rather than folklore.
_ISSUE_HINT = Suggestion(
    value=ISSUE_PREFIX, insert=ISSUE_PREFIX, label="issue.…", detail="Any field of the linked issue"
)


async def suggest_worklog(
    session: AsyncSession, *, actor: User, q: str, cursor: int | None
) -> SuggestResponse:
    position = len(q) if cursor is None else min(max(cursor, 0), len(q))
    detection = detect(q, position)

    # --- the delegated half -------------------------------------------------
    if detection.partial.startswith(ISSUE_PREFIX) or _field_is_delegated(detection):
        return await _delegate(session, actor=actor, q=q, cursor=position, detection=detection)

    if detection.context is SuggestContext.FIELD:
        return SuggestResponse(
            context=SuggestContext.FIELD,
            replace_from=detection.replace_from,
            suggestions=_rank(
                [
                    Suggestion(value=f.value, insert=f.value, label=f.value, detail=FIELD_LABELS[f])
                    for f in WorklogField
                    if f is not WorklogField.ISSUE
                ]
                + [
                    Suggestion(
                        value=WorklogField.ISSUE.value,
                        insert=WorklogField.ISSUE.value,
                        label="issue",
                        detail="The linked issue (IS EMPTY for general time)",
                    ),
                    _ISSUE_HINT,
                ],
                detection.partial,
            ),
        )

    if detection.context is SuggestContext.VALUE and detection.field:
        return SuggestResponse(
            context=SuggestContext.VALUE,
            replace_from=detection.replace_from,
            field=detection.field,
            suggestions=_rank(await _values(session, actor, detection.field), detection.partial),
        )

    if detection.context is SuggestContext.OPERATOR and detection.field:
        field = _worklog_field(detection.field)
        ops = WORKLOG_OPS[field] if field else None
        items = [Suggestion(value=op.value, insert=op.value, label=op.value, detail="") for op in (ops.compare if ops else ())]
        if ops and ops.membership:
            items.append(Suggestion(value="IN", insert="IN (", label="IN", detail=""))
        if ops and ops.empty:
            items.append(Suggestion(value="IS EMPTY", insert="IS EMPTY", label="IS EMPTY", detail=""))
        return SuggestResponse(
            context=SuggestContext.OPERATOR,
            replace_from=detection.replace_from,
            field=detection.field,
            suggestions=_rank(items, detection.partial),
        )

    return SuggestResponse(
        context=detection.context, replace_from=detection.replace_from, suggestions=[]
    )


def _field_is_delegated(detection) -> bool:
    return bool(detection.field) and detection.field.startswith(ISSUE_PREFIX)


async def _delegate(
    session: AsyncSession, *, actor: User, q: str, cursor: int, detection
) -> SuggestResponse:
    """Splice `issue.` out, ask the item suggester, shift the offset back.

    Removing a fixed-width prefix at a known offset means the mapping is just
    `+len(prefix)` for anything at or after it — no re-parsing, and the caller's
    `replace_from` still points at the character the user is actually editing
    (the part AFTER `issue.`), so the completion drops in without re-typing it.
    """
    cut = _prefix_start(q, cursor, detection)
    trimmed = q[:cut] + q[cut + len(ISSUE_PREFIX) :]
    inner_cursor = cursor - len(ISSUE_PREFIX) if cursor > cut else cursor
    inner = await suggestions_for(
        session,
        q=trimmed,
        cursor=max(inner_cursor, 0),
        scope=await _actor_scope(session, actor),
        definitions_by_key={},
    )
    shift = len(ISSUE_PREFIX) if inner.replace_from >= cut else 0
    return SuggestResponse(
        context=inner.context,
        replace_from=inner.replace_from + shift,
        field=f"{ISSUE_PREFIX}{inner.field}" if inner.field else None,
        suggestions=inner.suggestions,
    )


def _prefix_start(q: str, cursor: int, detection) -> int:
    """Where the `issue.` being completed begins."""
    if detection.partial.startswith(ISSUE_PREFIX):
        return detection.replace_from
    marker = q.rfind(ISSUE_PREFIX, 0, cursor)
    return marker if marker >= 0 else detection.replace_from


def _worklog_field(name: str) -> WorklogField | None:
    try:
        return WorklogField(name)
    except ValueError:
        return None


async def _values(session: AsyncSession, actor: User, field_name: str) -> list[Suggestion]:
    """Value completions for the worklog's OWN fields. `issue.` values come from
    the item dialect via the delegation, so they are absent here by design."""
    field = _worklog_field(field_name)
    if field is WorklogField.AUTHOR:
        people = (
            (await session.execute(select(User).where(User.active.is_(True)).limit(20)))
            .scalars()
            .all()
        )
        return [Suggestion(value="me", insert="me", label="me", detail="You")] + [
            Suggestion(value=u.email, insert=_quote(u.email), label=u.email, detail=u.name)
            for u in people
        ]
    if field is WorklogField.CATEGORY:
        cats = (await session.execute(select(WorkCategory).limit(50))).scalars().all()
        return [
            Suggestion(value=c.name, insert=_quote(c.name), label=c.name, detail="") for c in cats
        ]
    if field is WorklogField.PROJECT:
        # RADD-839: only projects the actor can read complete here.
        readable = frozenset(await authz.readable_projects(session, actor))
        projects = (
            (await session.execute(select(Project).where(Project.id.in_(readable)).limit(50)))
            .scalars()
            .all()
        )
        return [
            Suggestion(value=p.key, insert=p.key, label=p.key, detail=p.name) for p in projects
        ]
    return []


def _quote(text: str) -> str:
    return f'"{text}"' if any(ch.isspace() for ch in text) else text


def _rank(items: list[Suggestion], partial: str) -> list[Suggestion]:
    """Prefix matches first, then substring — the item dialect's ordering, so the
    two bars feel the same."""
    if not partial:
        return items
    needle = partial.lower()
    starts = [s for s in items if s.value.lower().startswith(needle)]
    contains = [s for s in items if needle in s.value.lower() and s not in starts]
    return starts + contains


async def _actor_scope(session: AsyncSession, actor: User) -> SuggestScope:
    """The delegated suggester runs project-UNSCOPED — a timesheet spans every
    project the actor can see, so narrowing to one project would hide exactly
    the cross-project rows the timesheet exists to show — but bounded by the
    actor's readable projects (RADD-839): keys+titles never complete from
    projects the actor can't read. `readable_projects` is request-memoised."""
    return SuggestScope(
        readable_project_ids=frozenset(await authz.readable_projects(session, actor))
    )


__all__ = ["suggest_worklog"]
