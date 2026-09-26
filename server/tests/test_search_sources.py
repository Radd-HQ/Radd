"""RADD-1384: search's documents and meaning arrive through kernel sockets (pages
provides SEARCH_DOCUMENTS, ai SEMANTIC_CANDIDATES), so a plugin disabled at runtime
stops feeding search — `settings.modules` is boot config and cannot see that. Each
test runs the SAME requests over the SAME rows with the plugin registered, then
withdrawn as the plugin manager does it, so neither half can pass vacuously.
DB-backed through the real app; flushed, never committed.
"""

import uuid

from radd.kernel import IntegrationSpec
from radd.kernel.registry import register_integration, registries
from radd.kernel.sockets import Socket
from radd.modules.ai import plugin as ai_plugin
from radd.modules.ai.embeddings import candidates
from radd.modules.items import service as items
from radd.modules.items.schemas import ItemCreate
from radd.modules.pages import plugin as pages_plugin
from radd.modules.pages.types import PageEntity
from radd.modules.projects import service as projects
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.search.indexer import _TSV_UPDATE
from radd.modules.search.models import SearchIndexRow
from test_authorization_surfaces import client_for
from test_page_restriction import _admin, _page, _space, db as db

_FAKE = "test_fake_semantic"


async def _project(db):
    return await projects.create_project(
        db, ProjectCreate(key="SS" + uuid.uuid4().hex[:6].upper(), name="Sources")
    )


async def _indexed_item(db, actor, project, title):
    """An item plus the search_index row the outbox indexer would write."""
    item = await items.create_item(db, ItemCreate(project_id=project.id, title=title), actor)
    db.add(SearchIndexRow(item_id=item.id, project_id=project.id, key=item.key, title=title))
    await db.flush()
    await db.execute(_TSV_UPDATE, {"item_id": item.id})
    return item


class _PageCandidates:
    """A semantic source naming one page — so a withdrawn document source is
    tested against a live candidate, not an empty list."""

    def __init__(self, page_id):
        self.page_id = page_id

    async def enabled(self, session):
        return True

    async def candidates(self, session, entity_type, q, *, limit, project_ids=None):
        return [(self.page_id, 0.1)] if entity_type == PageEntity.PAGE else []


async def _doc_ids(c, project, token):
    deflect = await c.get(
        "/api/v1/search/deflect", params={"project_id": str(project.id), "q": token}
    )
    ask = await c.get("/api/v1/search/semantic", params={"q": token})
    assert deflect.status_code == 200, deflect.text
    assert ask.status_code == 200, ask.text
    assert ask.json()["enabled"] is True
    return (
        [doc["id"] for doc in deflect.json()["docs"]],
        [doc["page_id"] for doc in ask.json()["docs"]],
    )


async def test_withdrawn_pages_contribute_no_documents(db):
    owner = await _admin(db)
    token = "zq" + uuid.uuid4().hex[:10]
    page = await _page(db, await _space(db, owner), owner, f"{token} handbook")
    project = await _project(db)
    # Registered AFTER the app is built: building it reloads the registries.
    async with client_for(db, owner) as c:
        register_integration(
            IntegrationSpec(Socket.SEMANTIC_CANDIDATES, _FAKE, impl=_PageCandidates(page.id))
        )
        try:
            assert await _doc_ids(c, project, token) == ([str(page.id)], [str(page.id)])

            registries.unregister_plugin(pages_plugin)
            try:
                assert registries.providers(Socket.SEARCH_DOCUMENTS) == {}
                assert await _doc_ids(c, project, token) == ([], [])
            finally:
                registries.register_plugin(pages_plugin)
        finally:
            registries.integrations.pop((Socket.SEMANTIC_CANDIDATES, _FAKE), None)


async def test_withdrawn_ai_leaves_search_full_text_only(db, monkeypatch):
    admin = await _admin(db)
    token = "zq" + uuid.uuid4().hex[:10]
    project = await _project(db)
    worded = await _indexed_item(db, admin, project, f"{token} printer exploded")
    lookalike = await _indexed_item(db, admin, project, "paper output charred")

    # The REAL ai provider, with its store and model stubbed: registered, it
    # fuses the lookalike in; withdrawn, these stubs are never reached.
    async def on(session):
        return True

    async def nearest(session, q, *, project_ids, exclude_item_id=None, limit):
        return [(lookalike.id, 0.1)]

    monkeypatch.setattr(candidates, "semantic_enabled", on)
    monkeypatch.setattr(candidates, "item_candidates", nearest)
    query = {"q": f"{token} printer"}
    async with client_for(db, admin) as c:
        hits = (await c.get("/api/v1/search", params=query)).json()["results"]
        assert {hit["key"] for hit in hits} == {worded.key, lookalike.key}
        ask = (await c.get("/api/v1/search/semantic", params=query)).json()
        assert ask["enabled"] is True
        assert [hit["key"] for hit in ask["items"]] == [lookalike.key]

        registries.unregister_plugin(ai_plugin)
        try:
            assert registries.providers(Socket.SEMANTIC_CANDIDATES) == {}
            response = await c.get("/api/v1/search", params=query)
            assert response.status_code == 200, response.text
            assert [hit["key"] for hit in response.json()["results"]] == [worded.key]
            ask = (await c.get("/api/v1/search/semantic", params=query)).json()
            assert ask == {"enabled": False, "items": [], "docs": []}
        finally:
            registries.register_plugin(ai_plugin)
