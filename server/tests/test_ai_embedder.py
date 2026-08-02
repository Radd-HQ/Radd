"""Semantic-search embedder (spec 103): event planning, the pgvector store, the
anti-join seams, and the hash-skip.

Vector-dependent tests run only when the `vector` extension is available on the
test server (the pgvector image); on plain Postgres they skip, mirroring the
feature's graceful absence. DDL is committed once per module (the throwaway
test DB is rebuilt every run); row-level work rolls back per test.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.db import SessionLocal
from radd.modules.ai.embeddings import embedder
from radd.modules.ai.embeddings import service as store

# --- pure ----------------------------------------------------------------------


def test_plan_for_event_mapping():
    item_id = str(uuid.uuid4())
    page_id = str(uuid.uuid4())
    assert embedder.plan_for_event("item.created", item_id, {}) == ("item", uuid.UUID(item_id))
    assert embedder.plan_for_event("item.updated", item_id, {}) == ("item", uuid.UUID(item_id))
    assert embedder.plan_for_event("comment.created", "77", {"item_id": item_id}) == (
        "item",
        uuid.UUID(item_id),
    )
    assert embedder.plan_for_event("item.deleted", item_id, {}) == (
        "drop_item",
        uuid.UUID(item_id),
    )
    assert embedder.plan_for_event("doc_page.updated", page_id, {}) == (
        "doc",
        uuid.UUID(page_id),
    )
    assert embedder.plan_for_event("doc_page.deleted", page_id, {}) == (
        "drop_doc",
        uuid.UUID(page_id),
    )
    assert embedder.plan_for_event("webhook.sent", item_id, {}) is None
    assert embedder.plan_for_event("comment.created", "x", {}) == ("item", None)
    assert embedder.plan_for_event("item.created", "not-a-uuid", {}) == ("item", None)


def test_embed_text_caps_and_hashes(monkeypatch):
    monkeypatch.setattr(settings, "ai_embed_max_chars", 20)
    text_value = embedder.embed_text("TD-1", "title", "d" * 100)
    assert len(text_value) == 20
    assert embedder.content_hash(text_value) == embedder.content_hash(text_value)
    assert embedder.content_hash("a") != embedder.content_hash("b")


def test_embed_text_is_identity_only():
    # Comment text stays OUT of vectors (imported boilerplate comments made
    # unrelated issues neighbors); the recipe is key + title + description.
    assert embedder.embed_text("TD-1", "Login fails", "500 on submit") == (
        "TD-1\nLogin fails\n500 on submit"
    )


def test_vector_literal_formatting():
    assert store.vector_literal([0.25, -1.0, 2]) == "[0.25,-1,2]"
    with pytest.raises(ValueError):
        store._validated("bad model!", 3)
    with pytest.raises(ValueError):
        store._validated("ok-model", 0)


# --- pgvector-backed (skip on plain Postgres) ----------------------------------


@pytest.fixture(scope="module")
async def schema():
    store.reset_availability_cache()
    async with SessionLocal() as session:
        ready = await store.ensure_schema(session)
        if ready:
            await session.commit()
    if not ready:
        pytest.skip("pgvector extension not available on the test server")


@pytest.fixture
async def db(schema):
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _work_item(db) -> tuple[uuid.UUID, uuid.UUID]:
    """A minimal committed-free item row pair (project, item) via raw inserts is
    overkill — reuse the ORM services would drag fixtures; embeddings only need
    ids that exist in work_items, so create the real thing."""
    from radd.modules.auth.models import User
    from radd.modules.auth.types import InstanceRole
    from radd.modules.items import service as items_service
    from radd.modules.items.schemas import ItemCreate
    from radd.modules.projects import service as projects_service
    from radd.modules.projects.schemas import ProjectCreate

    user = User(
        email=f"emb-{uuid.uuid4().hex[:8]}@example.com",
        name="Embedder",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"EM{uuid.uuid4().hex[:4].upper()}", name="Emb")
    )
    item = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="farm stalls overnight"), actor=user
    )
    return project.id, item.id


async def test_upsert_and_nearest_round_trip(db):
    project_id, item_id = await _work_item(db)
    _, other_item = await _work_item(db)
    model = "test-embed"
    await store.sync_index(db, store.ITEM_TABLE, model=model, dim=3)
    await store.upsert_item(
        db,
        item_id=item_id,
        project_id=project_id,
        model=model,
        content_hash="h1",
        embedding=[1.0, 0.0, 0.0],
    )
    other_project = (
        await db.execute(text("SELECT project_id FROM work_items WHERE id = :i"), {"i": other_item})
    ).scalar()
    await store.upsert_item(
        db,
        item_id=other_item,
        project_id=other_project,
        model=model,
        content_hash="h2",
        embedding=[0.0, 1.0, 0.0],
    )
    # Query near [1,0,0], readable = only the first project -> one hit, the item.
    hits = await store.nearest_items(
        db,
        [1.0, 0.0, 0.0],
        model=model,
        dim=3,
        project_ids=[project_id],
        exclude_item_id=None,
        limit=5,
    )
    assert [h[0] for h in hits] == [item_id]
    assert hits[0][1] == pytest.approx(0.0, abs=1e-6)
    # No readable projects -> empty, never an error.
    assert (
        await store.nearest_items(
            db, [1.0, 0.0, 0.0], model=model, dim=3, project_ids=[], exclude_item_id=None, limit=5
        )
        == []
    )
    # Model swap: the vector is invisible under another model's partial view.
    assert (
        await store.nearest_items(
            db,
            [1.0, 0.0, 0.0],
            model="other-model",
            dim=3,
            project_ids=[project_id],
            exclude_item_id=None,
            limit=5,
        )
        == []
    )
    # The stored vector reads back for the similar-issues seed.
    assert await store.item_embedding(db, item_id, model=model) == [1.0, 0.0, 0.0]
    assert await store.item_embedding(db, item_id, model="other-model") is None


async def test_search_seam_anti_join_finds_missing_and_model_stale(db):
    from radd.modules.search import service as search_service
    from radd.modules.search.models import SearchIndexRow

    project_id, item_id = await _work_item(db)
    db.add(
        SearchIndexRow(
            item_id=item_id,
            project_id=project_id,
            key="EM-1",
            title="farm stalls",
            description="nodes hang",
            comments_text="",
        )
    )
    await db.flush()
    missing = await search_service.rows_for_embedding(
        db, missing_from=store.ITEM_TABLE, model="test-embed", limit=50
    )
    assert any(r.item_id == item_id for r in missing)
    # Embedded under the active model -> no longer missing.
    await store.upsert_item(
        db,
        item_id=item_id,
        project_id=project_id,
        model="test-embed",
        content_hash="h",
        embedding=[0.1, 0.2, 0.3],
    )
    remaining = await search_service.rows_for_embedding(
        db, missing_from=store.ITEM_TABLE, model="test-embed", limit=50
    )
    assert not any(r.item_id == item_id for r in remaining)
    # ...but a MODEL CHANGE makes it missing again (the sweep re-embeds it).
    stale = await search_service.rows_for_embedding(
        db, missing_from=store.ITEM_TABLE, model="brand-new-model", limit=50
    )
    assert any(r.item_id == item_id for r in stale)
    with pytest.raises(ValueError):
        await search_service.rows_for_embedding(
            db, missing_from="bad; drop table x", model="m"
        )


async def test_hash_skip_only_reembeds_changed_rows(db):
    project_id, item_id = await _work_item(db)
    await store.upsert_item(
        db,
        item_id=item_id,
        project_id=project_id,
        model="m1",
        content_hash=embedder.content_hash("same text"),
        embedding=[0.1, 0.1, 0.1],
    )
    fresh = await embedder._fresh_indexes(
        db,
        store.ITEM_TABLE,
        "item_id",
        [item_id, uuid.uuid4()],
        [embedder.content_hash("same text"), embedder.content_hash("new")],
        "m1",
    )
    assert fresh == [1]  # unchanged row skipped, unknown row embedded
