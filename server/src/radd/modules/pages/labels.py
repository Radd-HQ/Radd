"""Page labels (RADD-718).

The tree can only express ONE hierarchy. Labels are the cross-cutting axis: a
`runbook` that lives under Operations is still a runbook when someone is looking
for every runbook in the wiki, whichever space it ended up in.

Reuses the `labels` module rather than growing a page-specific tag table — the
label rows, their colours and their names are shared with issues, so tagging a
page `incident` and an issue `incident` means the same thing. `resolve_labels`
is the find-or-create seam items already uses.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.labels import service as labels_service
from radd.modules.labels.models import Label

from .models import Page, PageLabel, PageSpace
from .schemas import PageLabelled


async def labels_of(session: AsyncSession, page_id: uuid.UUID) -> list[Label]:
    rows = await session.execute(
        select(Label)
        .join(PageLabel, PageLabel.label_id == Label.id)
        .where(PageLabel.page_id == page_id)
        .order_by(Label.name)
    )
    return list(rows.scalars())


async def labels_for_pages(
    session: AsyncSession, page_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[str]]:
    """One query for a whole tree — the space view shows labels per row, and a
    query per row is how a 200-page space becomes slow."""
    if not page_ids:
        return {}
    rows = await session.execute(
        select(PageLabel.page_id, Label.name)
        .join(Label, Label.id == PageLabel.label_id)
        .where(PageLabel.page_id.in_(page_ids))
        .order_by(Label.name)
    )
    out: dict[uuid.UUID, list[str]] = {}
    for page_id, name in rows.all():
        out.setdefault(page_id, []).append(name)
    return out


async def set_labels(
    session: AsyncSession, page_id: uuid.UUID, names: Sequence[str], actor_id: uuid.UUID
) -> list[Label]:
    """Full replacement, matching how items take labels — a partial-update API
    for a set makes "remove the last one" ambiguous."""
    labels = await labels_service.resolve_labels(session, names, actor_id=actor_id)
    await session.execute(delete(PageLabel).where(PageLabel.page_id == page_id))
    for label in labels:
        session.add(PageLabel(page_id=page_id, label_id=label.id))
    await session.flush()
    return sorted(labels, key=lambda label: label.name)


async def pages_with_label(
    session: AsyncSession,
    name: str,
    space_slug: str = "",
    *,
    space_ids: "set[uuid.UUID] | None" = None,
) -> list[PageLabelled]:
    """Every live page carrying `name`, optionally within one space.

    This is what `radd:label-list` renders — the "content by label" pattern that
    lets an index page maintain itself instead of being hand-curated.
    """
    query = (
        select(Page, PageSpace.slug)
        .join(PageLabel, PageLabel.page_id == Page.id)
        .join(Label, Label.id == PageLabel.label_id)
        .join(PageSpace, PageSpace.id == Page.space_id)
        .where(Label.name == name, Page.archived_at.is_(None))
        .order_by(Page.title)
    )
    if space_slug:
        query = query.where(PageSpace.slug == space_slug)
    # RADD-791: only spaces the reader may see. A self-maintaining index page
    # that listed titles out of a space someone cannot open would leak exactly
    # what the space boundary exists to hold.
    if space_ids is not None:
        query = query.where(Page.space_id.in_(space_ids))
    rows = await session.execute(query)
    return [
        PageLabelled(
            id=page.id,
            title=page.title,
            slug=page.slug,
            space_slug=slug,
            updated_at=page.updated_at,
        )
        for page, slug in rows.all()
    ]
