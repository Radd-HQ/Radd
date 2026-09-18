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

from radd.kernel import changes
from radd.modules.events import service as events
from radd.modules.labels import service as labels_service
from radd.modules.labels.service import Label

from .models import Page, PageLabel, PageSpace
from .schemas import PageLabelled
from .types import PageEntity, PageEvent


async def labels_of(session: AsyncSession, page_id: uuid.UUID) -> list[Label]:
    label_ids = list(
        (
            await session.execute(
                select(PageLabel.label_id).where(PageLabel.page_id == page_id)
            )
        ).scalars()
    )
    found = await labels_service.labels_by_ids(session, label_ids)
    return sorted(found.values(), key=lambda label: label.name)


async def labels_for_pages(
    session: AsyncSession, page_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[str]]:
    """Two fixed queries for a whole tree (our rows, then the labels batch) —
    the space view shows labels per row, and a query per row is how a 200-page
    space becomes slow."""
    if not page_ids:
        return {}
    rows = (
        await session.execute(
            select(PageLabel.page_id, PageLabel.label_id).where(
                PageLabel.page_id.in_(page_ids)
            )
        )
    ).all()
    if not rows:
        return {}
    labels = await labels_service.labels_by_ids(session, [lid for _, lid in rows])
    out: dict[uuid.UUID, list[str]] = {}
    for page_id, label_id in rows:
        label = labels.get(label_id)
        if label is not None:
            out.setdefault(page_id, []).append(label.name)
    for names in out.values():
        names.sort()
    return out


async def set_labels(
    session: AsyncSession, page_id: uuid.UUID, names: Sequence[str], actor_id: uuid.UUID
) -> list[Label]:
    """Full replacement, matching how items take labels — a partial-update API
    for a set makes "remove the last one" ambiguous."""
    before = sorted(label.name for label in await labels_of(session, page_id))
    labels = await labels_service.resolve_labels(session, names, actor_id=actor_id)
    await session.execute(delete(PageLabel).where(PageLabel.page_id == page_id))
    for label in labels:
        session.add(PageLabel(page_id=page_id, label_id=label.id))
    await session.flush()
    result = sorted(labels, key=lambda label: label.name)
    # Spec 123: a label change is a page update with an added/removed diff —
    # it used to leave no event at all.
    entry = changes.collection_change("labels", before, [label.name for label in result])
    if entry is not None:
        page = await session.get(Page, page_id)
        await events.emit(
            session,
            event_type=PageEvent.PAGE_UPDATED,
            entity_type=PageEntity.PAGE,
            entity_id=page_id,
            actor_id=actor_id,
            subjects={"page": page_id, "page_space": page.space_id if page else None},
            changes=[entry],
        )
    return result


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
    label = await labels_service.label_by_name(session, name)
    if label is None:  # same answer the old Label.name join gave: no rows
        return []
    query = (
        select(Page, PageSpace.slug)
        .join(PageLabel, PageLabel.page_id == Page.id)
        .join(PageSpace, PageSpace.id == Page.space_id)
        .where(PageLabel.label_id == label.id, Page.archived_at.is_(None))
        .order_by(Page.title)
    )
    if space_slug:
        query = query.where(PageSpace.slug == space_slug)
    # RADD-791: only spaces the reader may see. A self-maintaining index page
    # that listed titles out of a space someone cannot open would leak exactly
    # what the space boundary exists to hold.
    if space_ids is not None:
        query = query.where(Page.space_id.in_(space_ids))
    pairs = (await session.execute(query)).all()
    from . import paths

    page_paths = await paths.paths_for(session, [page for page, _ in pairs])
    return [
        PageLabelled(
            id=page.id,
            number=page.number,
            title=page.title,
            slug=page.slug,
            path=page_paths[page.id],
            space_slug=slug,
            updated_at=page.updated_at,
        )
        for page, slug in pairs
    ]
