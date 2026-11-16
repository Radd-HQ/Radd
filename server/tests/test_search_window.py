"""Full-text search ranks a window of the newest matches (RADD-1533).

`ts_rank_cd` reads every match's tsvector. A common word matched 223k of 501k
rows, and ranking all of them before the LIMIT took 1.9 s. The window bounds
that work; these tests pin what it may and may not change.
"""

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import update

from _factories import make_project
from radd.config import settings
from radd.modules import workflow as _workflow  # noqa: F401 — the project.created hook seeds states
from radd.modules.items import service as items
from radd.modules.items.schemas import ItemCreate
from radd.modules.search import indexer
from radd.modules.search import service as search
from radd.modules.search.models import SearchIndexRow

WORD = "windowquokka"


def _event(item, project):
    return SimpleNamespace(
        entity_id=str(item.id),
        payload={"item": {
            "id": str(item.id),
            "project": {"id": str(project.id), "key": project.key, "name": project.name},
            "key": item.key, "title": item.title, "description": "",
            "reporter": None, "assignee": None, "team": None,
        }},
    )


async def _indexed(db, admin, titles: list[str]):
    """Items indexed oldest first: each a day newer than the one before."""
    project = await make_project(db, "SW", actor=admin)
    start = datetime(2026, 1, 1)
    rows = []
    for offset, title in enumerate(titles):
        item = await items.create_item(db, ItemCreate(project_id=project.id, title=title), admin)
        await indexer._index_item(db, _event(item, project))
        await db.execute(
            update(SearchIndexRow)
            .where(SearchIndexRow.item_id == item.id)
            .values(updated_at=start + timedelta(days=offset))
        )
        rows.append(item)
    await db.flush()
    return rows


async def test_fewer_matches_than_the_window_are_all_ranked(db, admin):
    oldest, middle, newest = await _indexed(db, admin, [
        f"{WORD} {WORD} {WORD} oldest and most relevant", f"{WORD} middle", f"{WORD} newest",
    ])
    assert settings.search_rank_candidates > 3
    hits = [hit.item_id for hit in await search.search(db, admin, WORD)]
    assert set(hits) == {oldest.id, middle.id, newest.id}
    assert hits[0] == oldest.id, "relevance no longer leads when everything fits the window"


async def test_a_common_word_is_ranked_within_its_newest_matches(db, admin, monkeypatch):
    oldest, middle, newest = await _indexed(db, admin, [
        f"{WORD} {WORD} {WORD} oldest and most relevant", f"{WORD} middle", f"{WORD} newest",
    ])
    monkeypatch.setattr(settings, "search_rank_candidates", 2)
    # `limit` is part of the floor (`max(window, limit)`), so ask for fewer than the window.
    hits = [hit.item_id for hit in await search.search(db, admin, WORD, limit=2)]
    assert set(hits) == {middle.id, newest.id}, "the window is not the two newest matches"


async def test_the_window_never_cuts_below_the_page_asked_for(db, admin, monkeypatch):
    rows = await _indexed(db, admin, [f"{WORD} number {index}" for index in range(5)])
    monkeypatch.setattr(settings, "search_rank_candidates", 1)
    hits = await search.search(db, admin, WORD, limit=5)
    assert {hit.item_id for hit in hits} == {row.id for row in rows}
    assert uuid.UUID(str(hits[0].item_id))  # a real page, not a truncated one
