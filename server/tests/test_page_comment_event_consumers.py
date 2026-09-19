"""RADD-1247: a page comment's event carries `item: None`; the two consumers
that read the item ref must step over it rather than crash (they crashed on
every page comment since 2026-08, two tracebacks per comment, cursor advancing
so nobody noticed)."""

from types import SimpleNamespace

from radd.modules.mailintake import outbound
from radd.modules.search import indexer


def _page_comment_event():
    return SimpleNamespace(
        id=1,
        event_type="comment.created",
        entity_id="00000000-0000-4000-8000-000000000001",
        actor_id=None,
        payload={"entity_type": "page", "entity_id": "00000000-0000-4000-8000-000000000002", "item": None},
    )


async def test_the_search_indexer_steps_over_a_page_comment():
    # No session is touched before the early return — None proves it.
    await indexer._reindex_comments(None, _page_comment_event())


async def test_the_outbound_planner_steps_over_a_page_comment():
    assert await outbound._plan_reply(None, _page_comment_event()) is None
