"""What the classifier node actually sends the model (spec 116).

The first version sent `"3 item(s)"` — the COUNT and nothing else — while its
docstring and its form hint both promised "the item summaries". A prompt asking
"is this a bug report or a feature request?" against a bare count can only
produce noise, and nothing in the run report would have shown why.

So the payload is built here, explicitly, and the node's form says which parts
are included. Three rules shape it:

* **Include only what was asked for.** Every section is a checkbox on the node.
  Sending comments and worklogs to a provider when the question is about titles
  is a privacy cost with no benefit, and on a self-hosted instance the admin is
  the one who gets to weigh that.
* **Budget WHOLE items, never fields.** The first version capped descriptions at
  600 characters and comments at five per item — numbers invented here with a
  justification written after the fact. Truncating a description mid-sentence can
  cut the exact line that decides "bug or feature", and no budget arithmetic makes
  that a good trade. An item is included entirely or not at all.
* **The limit is a setting, not a constant.** The real constraint is the
  configured model's context window, which the provider registry does not record —
  so `ai_automation_context_chars` is a tunable you size to your model rather than
  a number this file pretends to know.
* **Say what was cut.** A digest that quietly omits half the items produces a
  confident answer about evidence the model never saw, so the omission is stated
  IN THE PROMPT.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.modules.auth.models import User

#: Hard ceiling on how many items are even considered, independent of the
#: character budget — a 200-item scheduled run should not build a 200-item string
#: only to discard most of it. Sized to `automation_schedule_max_items` so the
#: two caps cannot silently disagree about what "all the items" means.
MAX_ITEMS = 200


@dataclass(frozen=True)
class ContextOptions:
    """Which sections of an item the model sees. Mirrors the node's checkboxes."""

    fields: bool = True  # type, state, priority, assignee, labels, custom fields
    description: bool = True
    comments: bool = False
    worklogs: bool = False

    @classmethod
    def from_params(cls, params: dict[str, Any]) -> "ContextOptions":
        # A stored `include` that is not a mapping falls back to the defaults
        # rather than raising (RADD-1064). The generated form used to render this
        # object property as a free-text input, so instances hold nodes whose
        # `include` is a STRING someone typed — and `"…".get` is an
        # AttributeError inside `_ask`, which the node catches as "the provider
        # is unavailable". A misdrawn form would have become a permanently
        # dormant AI check with an outage's error message.
        raw = params.get("include")
        include: dict[str, Any] = raw if isinstance(raw, dict) else {}
        return cls(
            fields=bool(include.get("fields", True)),
            description=bool(include.get("description", True)),
            comments=bool(include.get("comments", False)),
            worklogs=bool(include.get("worklogs", False)),
        )


def _render_item(read: Any, comments: list[Any], options: ContextOptions, worklog: str | None) -> str:
    """One item, WHOLE. Nothing here truncates: the budget is spent by dropping
    items, so what the model sees of an item is what the item says."""
    lines = [f"--- {read.key}: {read.title}"]
    if options.fields:
        facts = [f"type={read.kind}", f"state={read.state.name}", f"priority={read.priority}"]
        if read.assignee:
            facts.append(f"assignee={read.assignee.name}")
        if read.labels:
            facts.append(f"labels={', '.join(read.labels)}")
        for key, value in (read.custom_fields or {}).items():
            if value not in (None, "", []):
                facts.append(f"{key}={value}")
        lines.append("  " + "; ".join(facts))
    if options.description and read.description:
        lines.append(f"  description: {read.description.strip()}")
    for comment in comments:
        lines.append(f"  comment by {comment.author.name}: {comment.body.strip()}")
    if worklog is not None:
        lines.append(f"  time logged: {worklog}")
    return "\n".join(lines)


async def build_context(
    session: AsyncSession,
    item_ids: tuple[uuid.UUID, ...],
    actor: User,
    options: ContextOptions,
) -> str:
    """A plain-text digest of the items, honouring `options`.

    Reads go through the item/comment services with `actor`, so the digest can
    only ever contain what that identity could already see — the same property
    the Summarize feature relies on. An automation running as someone with
    narrow access sends a correspondingly narrow prompt.
    """
    from radd.modules.comments import service as comments_service
    from radd.modules.items import service as items_service

    if not item_ids:
        return "No items matched this run."

    budget = settings.ai_automation_context_chars
    considered = item_ids[:MAX_ITEMS]
    blocks: list[str] = []
    spent = 0
    omitted = len(item_ids) - len(considered)

    for index, item_id in enumerate(considered):
        try:
            read = await items_service.get_item(session, item_id, actor)
        except Exception:  # noqa: BLE001 — deliberate: an item that vanished mid-run,
            # or that this identity may not read, is simply absent from the prompt.
            # Failing the whole classification because one of 40 items moved would
            # turn a routing decision into an outage.
            continue

        comments: list[Any] = []
        if options.comments:
            try:
                comments = list(await comments_service.list_comments(session, item_id, actor))
            except Exception:  # noqa: BLE001 — deliberate: comments are an OPTIONAL
                # section. Omitting them degrades the prompt; raising would drop the
                # classification entirely.
                comments = []
        worklog = await _worklog_line(session, item_id, read) if options.worklogs else None

        block = _render_item(read, comments, options, worklog)
        if blocks and spent + len(block) > budget:
            # The budget is spent on whole items, so the rest are omitted rather
            # than the current one being cut in half. `blocks and` keeps a single
            # oversized item from producing an empty digest — one item over
            # budget is still a better prompt than none.
            omitted += len(considered) - index
            break
        blocks.append(block)
        spent += len(block)

    if omitted:
        # Stated in the PROMPT, not just logged: the model is answering about a
        # sample, and a confident answer about part of the set should say so.
        blocks.append(
            f"\n({omitted} further item(s) not shown — the prompt reached its "
            f"{budget}-character budget. Raise RADD_AI_AUTOMATION_CONTEXT_CHARS if "
            f"your model has room.)"
        )
    return "\n".join(blocks)


async def _worklog_line(session: AsyncSession, item_id: uuid.UUID, read: Any) -> str:
    """Total logged time, feature-detected — a project that does not track time
    has no worklogs, and the section should say so rather than read as zero."""
    try:
        from radd.modules.timelogging import service as timelogging

        summary = await timelogging.item_summary(session, item_id, read.project_id)
    except Exception:  # noqa: BLE001 — deliberate: time tracking is per-project
        # optional, so "no worklog data" is a normal answer, not an error. Reported
        # as "not tracked" rather than 0h, which would read as "nobody logged time".
        return "not tracked"
    total = getattr(summary, "total_seconds", 0) or 0
    return f"{round(total / 3600, 1)}h" if total else "none"
