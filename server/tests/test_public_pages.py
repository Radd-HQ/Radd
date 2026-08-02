"""Public knowledge base (spec 74), driven through the real services against
live Postgres in a rolled-back transaction (nothing persists):

- non-public spaces 404 on tree/page and are excluded from the search scope,
- archived pages are invisible publicly (tree, page, search),
- public search hits public spaces only (+ the optional space pin),
- toggling `public` off immediately 404s the public reads (no caching layer),
- the tokened form deflect returns public-KB hits and 404s on a bad token.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import ConflictError, NotFoundError
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.pages import public as kb, service as docs_service, spaces as docs_spaces
from radd.modules.pages.models import PageSpace
from radd.modules.pages.schemas import PageCreate, PageSpaceCreate, PageSpaceUpdate
from radd.modules.forms import public as forms_public, service as forms_service
from radd.modules.forms.schemas import FormCreate, FormUpdate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def admin(db) -> User:
    user = User(
        email=f"kb-{uuid.uuid4().hex[:8]}@example.com",
        name="Public KB Admin",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _space(db, admin, *, public: bool, name: str) -> PageSpace:
    space = await docs_spaces.create_space(
        db,
        PageSpaceCreate(name=f"{name} {uuid.uuid4().hex[:6]}"),
        admin.id,
    )
    if public:
        await docs_spaces.update_space(db, space.id, PageSpaceUpdate(public=True), admin.id)
    return space


async def _page(db, admin, space, title: str, body: str = "", parent_id=None):
    return await docs_service.create_page(
        db,
        PageCreate(space_id=space.id, parent_id=parent_id, title=title, body=body),
        admin.id,
    )


# --- space scope: public flag is the credential ---


async def test_only_public_spaces_are_listed(db, admin):
    public_space = await _space(db, admin, public=True, name="Handbook")
    private_space = await _space(db, admin, public=False, name="Internal")
    listed = {space.id for space in await kb.list_public_spaces(db)}
    assert public_space.id in listed
    assert private_space.id not in listed


async def test_non_public_space_404s_tree_and_page(db, admin):
    private_space = await _space(db, admin, public=False, name="Internal")
    page = await _page(db, admin, private_space, "Secret runbook", "internal only")

    with pytest.raises(NotFoundError):
        await kb.public_tree(db, private_space.id)
    with pytest.raises(NotFoundError):
        await kb.public_page(db, page.id)
    with pytest.raises(NotFoundError):  # unknown space reads the same as private
        await kb.public_tree(db, uuid.uuid4())


async def test_archived_page_is_invisible_publicly(db, admin):
    term = f"quokka{uuid.uuid4().hex[:6]}"
    space = await _space(db, admin, public=True, name="Handbook")
    live = await _page(db, admin, space, f"Live {term}", "kept visible")
    doomed = await _page(db, admin, space, f"Old {term}", "to be archived")
    await docs_service.archive_page(db, doomed.id, admin.id)

    tree_ids = {node.id for node in await kb.public_tree(db, space.id)}
    assert live.id in tree_ids and doomed.id not in tree_ids
    with pytest.raises(NotFoundError):
        await kb.public_page(db, doomed.id)
    assert {hit.page_id for hit in await kb.search_public(db, term)} == {live.id}


async def test_search_hits_public_spaces_only(db, admin):
    term = f"wombat{uuid.uuid4().hex[:6]}"
    public_space = await _space(db, admin, public=True, name="Handbook")
    private_space = await _space(db, admin, public=False, name="Internal")
    public_page = await _page(db, admin, public_space, f"Guide to {term}", "answers")
    await _page(db, admin, private_space, f"Internal {term} notes", "secrets")

    hits = await kb.search_public(db, term)
    assert {hit.page_id for hit in hits} == {public_page.id}

    # The optional space pin works — and can't probe a private space.
    pinned = await kb.search_public(db, term, space_id=public_space.id)
    assert {hit.page_id for hit in pinned} == {public_page.id}
    with pytest.raises(NotFoundError):
        await kb.search_public(db, term, space_id=private_space.id)


async def test_toggling_public_off_immediately_404s(db, admin):
    space = await _space(db, admin, public=True, name="Handbook")
    page = await _page(db, admin, space, "Setup guide", "how to set up")
    assert await kb.public_page(db, page.id)  # readable while public

    await docs_spaces.update_space(db, space.id, PageSpaceUpdate(public=False), admin.id)
    with pytest.raises(NotFoundError):
        await kb.public_tree(db, space.id)
    with pytest.raises(NotFoundError):
        await kb.public_page(db, page.id)


# --- the tokened form deflect (public router seam) ---


async def _public_form(db, admin) -> tuple[uuid.UUID, str]:
    """A publicly-enabled form; returns (form_id, token)."""
    project = await projects_service.create_project(
        db,
        ProjectCreate(key=f"K{uuid.uuid4().hex[:4].upper()}", name="Desk"),
    )
    form = await forms_service.create_form(
        db, FormCreate(project_id=project.id, name="Support"), admin
    )
    enabled = await forms_service.update_form(db, form.id, FormUpdate(allow_public=True), admin)
    assert enabled.public_token is not None
    return form.id, enabled.public_token


async def test_form_deflect_returns_public_kb_hits_only(db, admin):
    term = f"numbat{uuid.uuid4().hex[:6]}"
    space = await _space(db, admin, public=True, name="Handbook")
    page = await _page(db, admin, space, f"Fixing {term}", "the answer")
    private_space = await _space(db, admin, public=False, name="Internal")
    await _page(db, admin, private_space, f"Private {term}", "internal")
    _, token = await _public_form(db, admin)

    result = await forms_public.deflect_public_form(db, token, term)
    assert [(doc.id, doc.space_id) for doc in result.docs] == [(page.id, space.id)]
    assert result.docs[0].space_name == space.name

    # Blank query short-circuits; bad token 404s; disabled form 409s.
    assert (await forms_public.deflect_public_form(db, token, "   ")).docs == []
    with pytest.raises(NotFoundError):
        await forms_public.deflect_public_form(db, "not-a-real-token", term)


async def test_form_deflect_respects_the_form_gate(db, admin):
    form_id, token = await _public_form(db, admin)
    await forms_service.update_form(db, form_id, FormUpdate(enabled=False), admin)
    with pytest.raises(ConflictError):
        await forms_public.deflect_public_form(db, token, "anything")


async def test_form_deflect_fuses_public_semantic_candidates(db, admin, monkeypatch):
    """Spec 106: public deflection fuses public-only semantic candidates — and
    re-checks the LIVE space flag, so a private page the (stale) vector store
    offers never reaches the anonymous visitor."""
    from radd.modules.ai.embeddings import candidates

    term = f"wombat{uuid.uuid4().hex[:6]}"
    space = await _space(db, admin, public=True, name="Handbook")
    fts_page = await _page(db, admin, space, f"Fixing {term}", "the answer")
    lookalike = await _page(db, admin, space, "Adjacent lore", "related content")
    private_space = await _space(db, admin, public=False, name="Internal")
    private_page = await _page(db, admin, private_space, "Secret fix", "internal")
    _, token = await _public_form(db, admin)

    seen: dict[str, bool] = {}

    async def fake_enabled(session):
        return True

    async def fake_doc_candidates(session, q, *, public_only, limit):
        seen["public_only"] = public_only
        return [(lookalike.id, 0.1), (private_page.id, 0.2)]

    monkeypatch.setattr(candidates, "semantic_enabled", fake_enabled)
    monkeypatch.setattr(candidates, "doc_candidates", fake_doc_candidates)

    result = await forms_public.deflect_public_form(db, token, term)
    assert [doc.id for doc in result.docs] == [fts_page.id, lookalike.id]
    assert seen["public_only"] is True

    async def broken(session, q, *, public_only, limit):
        raise RuntimeError("provider down")

    monkeypatch.setattr(candidates, "doc_candidates", broken)
    result = await forms_public.deflect_public_form(db, token, term)
    assert [doc.id for doc in result.docs] == [fts_page.id]
