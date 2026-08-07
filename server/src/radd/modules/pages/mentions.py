"""Issues a page's text mentions, kept as links (RADD-943).

A page that names twelve issues in its body and shows "No linked issues yet" is
keeping the same fact twice and letting one copy rot. This reconciles the
DERIVED half of `item_page_links` from the body on every save, exactly as
`backlinks.reindex` reconciles page→page references and
`items.service.links.sync_mention_links` reconciles item→item ones.

Three rules, and the whole design is in them:

* **Derived rows are owned by the text.** They are replaced wholesale, so
  removing a mention removes the link. Diffing would leave a phantom link nobody
  could explain by reading the page.
* **Manual rows are never touched**, and a key that is both mentioned and
  manually linked stays manual. Someone typed that key; a body edit must not be
  able to undo it.
* **An unresolvable key is dropped, not raised.** Referencing an issue that does
  not exist (a typo, another instance's key, an issue since hard-deleted) is
  ordinary text, not a reason to fail the save.

No permission check: this is a derived index, and the READ (`links.linked_items`)
already filters to the projects the caller may see, which is where the gate
belongs — a page must index what it says regardless of who saved it.

It lives beside `links.py` rather than in it because `links.py` imports
`service.get_page`, and `service` is what calls this.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.items import service as items_service
from radd.modules.items.mentions import parse_issue_keys

from .models import ItemPageLink, Page


async def referenced_item_ids(session: AsyncSession, body: str) -> set[uuid.UUID]:
    """The item ids `body` references, in either mention form."""
    resolved: set[uuid.UUID] = set()
    for key in parse_issue_keys(body):
        item = await items_service.find_item_by_key(session, key)
        if item is not None:
            resolved.add(item.id)
    return resolved


async def reindex(session: AsyncSession, page: Page) -> None:
    """Replace this page's derived issue links. Called from the page write path
    wherever the body changed."""
    desired = await referenced_item_ids(session, page.body)
    rows = list(
        (
            await session.execute(
                select(ItemPageLink).where(ItemPageLink.page_id == page.id)
            )
        ).scalars()
    )
    desired -= {row.item_id for row in rows if not row.derived}
    existing = {row.item_id: row for row in rows if row.derived}
    for item_id, row in existing.items():
        if item_id not in desired:
            await session.delete(row)
    for item_id in desired - set(existing):
        session.add(
            ItemPageLink(
                item_id=item_id,
                page_id=page.id,
                # The editor whose save produced the row. Nobody "made" a
                # derived link, but the column is NOT NULL and this is the
                # closest true answer.
                created_by=page.updated_by,
                derived=True,
            )
        )
    await session.flush()


async def reindex_all(session: AsyncSession) -> int:
    """Rebuild every live page's derived links. Derived data, so this is always
    safe; it exists for content that never passed the save path — pages written
    before RADD-943, and anything an importer created."""
    pages = list(
        (await session.execute(select(Page).where(Page.archived_at.is_(None)))).scalars()
    )
    for page in pages:
        await reindex(session, page)
    return len(pages)
