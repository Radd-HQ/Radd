"""The import run, end to end over a cached snapshot (spec 117).

No network: a snapshot is just rows, so these build one directly and run the real
pipeline over it. That is the same property the importer sells — everything after
the download reads the cache — used here to make the pipeline testable.

The assertions that matter are the ones about what happens when something goes
WRONG: a restricted page whose principal does not resolve must not be created, and
a second run must update rather than duplicate.
"""

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.confluenceimport import plan as plan_service, runs
from radd.modules.confluenceimport.models import (
    ConfluenceSnapshot,
    ConfluenceSnapshotPage,
)
from radd.modules.confluenceimport.schemas import PlanCreate, PlanOptions
from radd.modules.confluenceimport.types import (
    RunStage,
    ScopeKind,
    SnapshotStage,
    UnresolvedPrincipal,
)
from radd.modules.pages.models import Page, PageSpace

SOURCE = "confluence:wiki.example.test"

RESTRICTED = {
    "read": {
        "restrictions": {
            "user": {"results": []},
            "group": {"results": [{"name": "a-group-that-does-not-exist"}]},
        }
    }
}


@pytest.fixture
async def db():
    """A session that CLEANS UP, because the pipeline commits.

    Every other suite here is isolated by rollback, which works only while the
    code under test does not commit. A real run does — the row is its progress
    bar — so these tests leave spaces and pages behind unless they remove them,
    and a neighbouring suite that counts spaces then fails for a reason that has
    nothing to do with it. Everything this file creates is stamped with `SOURCE`,
    which makes the cleanup exact.
    """
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
        spaces = list(
            (
                await session.execute(
                    select(PageSpace).where(PageSpace.external_source == SOURCE)
                )
            ).scalars()
        )
        for space in spaces:  # pages, versions and grants cascade
            await session.delete(space)
        for snapshot in list(
            (
                await session.execute(
                    select(ConfluenceSnapshot).where(
                        ConfluenceSnapshot.external_source == SOURCE
                    )
                )
            ).scalars()
        ):
            await session.delete(snapshot)
        await session.commit()
    await engine.dispose()


async def _admin(db) -> User:
    user = User(
        email=f"imp-{uuid.uuid4().hex[:8]}@example.com",
        name="Importer",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _snapshot(db, actor, pages: list[dict]) -> ConfluenceSnapshot:
    """A finished snapshot, built directly — no client, no network.

    Page ids are made unique per snapshot. They are unique instance-wide in real
    Confluence, and the run COMMITS, so reusing a bare "1" across tests makes the
    second test's page resolve — correctly! — to the first test's import via the
    external identity, and land in the wrong space.
    """
    key = f"SP{uuid.uuid4().hex[:6].upper()}"
    prefix = uuid.uuid4().hex[:8]
    pages = [
        {**page,
         "id": f"{prefix}{page['id']}",
         "parent": f"{prefix}{page['parent']}" if page.get("parent") else None}
        for page in pages
    ]
    snapshot = ConfluenceSnapshot(
        actor_id=actor.id,
        name="test",
        scope={"kind": ScopeKind.SPACE.value, "space_key": key, "page_ids": []},
        external_source=SOURCE,
        base_url="https://wiki.example.test",
        stage=SnapshotStage.DONE.value,
        counts={}, problems=[], catalogs={},
        include_attachments=False, include_comments=False,
    )
    db.add(snapshot)
    await db.flush()
    for index, page in enumerate(pages):
        db.add(ConfluenceSnapshotPage(
            snapshot_id=snapshot.id,
            page_id=page["id"],
            space_key=key,
            parent_id=page.get("parent"),
            title=page["title"],
            position=index,
            version=page.get("version", 1),
            body=page.get("body", "<p>hello</p>"),
            payload={},
            versions=page.get("versions", []),
            restrictions=page.get("restrictions", {}),
            labels=[],
        ))
    await db.flush()
    return snapshot


async def _run(db, snapshot, actor, *, dry_run=False, options: PlanOptions | None = None):
    plan = await plan_service.create_plan(
        db, PlanCreate(name=f"plan-{uuid.uuid4().hex[:6]}", snapshot_id=snapshot.id)
    )
    if options is not None:
        plan.options = options.model_dump(mode="json")
    await db.flush()
    run = await runs.start_run(db, plan.id, dry_run=dry_run, actor_id=actor.id)
    await db.flush()
    # Drive the pipeline directly rather than through `start()`: the fire-and-
    # forget task would open its OWN session and never see this transaction.
    await runs._pipeline(db, run)
    return run


async def _pages_in(db, snapshot) -> list[Page]:
    space = await db.scalar(
        select(PageSpace).where(
            PageSpace.external_source == SOURCE,
            PageSpace.external_id == snapshot.scope["space_key"],
        )
    )
    if space is None:
        return []
    return list(
        (await db.execute(select(Page).where(Page.space_id == space.id))).scalars()
    )


# --- the happy path ---


async def test_a_space_imports_with_its_tree_shape(db):
    actor = await _admin(db)
    snapshot = await _snapshot(db, actor, [
        {"id": "1", "title": "Root", "body": "<h2>Root</h2><p>top</p>"},
        {"id": "2", "title": "Child", "parent": "1", "body": "<p>under root</p>"},
    ])
    run = await _run(db, snapshot, actor)

    assert RunStage(run.stage) is RunStage.DONE, run.problems
    pages = await _pages_in(db, snapshot)
    assert {p.title for p in pages} == {"Root", "Child"}
    root = next(p for p in pages if p.title == "Root")
    child = next(p for p in pages if p.title == "Child")
    assert child.parent_id == root.id, "the tree shape is the point"
    assert "## Root" in root.body, "the body went through the converter"
    # The external identity is what every later run resolves against.
    assert root.external_source == SOURCE
    assert root.external_id == next(
        r.page_id for r in (await db.execute(
            select(ConfluenceSnapshotPage).where(
                ConfluenceSnapshotPage.snapshot_id == snapshot.id,
                ConfluenceSnapshotPage.title == "Root",
            )
        )).scalars()
    )


async def test_a_dry_run_predicts_and_writes_nothing(db):
    """The counts are measured by doing all the work except the write, so they are
    facts rather than estimates."""
    actor = await _admin(db)
    snapshot = await _snapshot(db, actor, [
        {"id": "1", "title": "One"}, {"id": "2", "title": "Two"},
    ])
    run = await _run(db, snapshot, actor, dry_run=True)

    assert run.counts.get("pages_created") == 2
    assert await _pages_in(db, snapshot) == []


# --- re-import ---


async def test_a_second_run_updates_rather_than_duplicating(db):
    """The whole reason `pages.external_id` exists. Without it the second run
    cannot tell its own earlier output from a page somebody wrote by hand."""
    actor = await _admin(db)
    snapshot = await _snapshot(db, actor, [{"id": "1", "title": "One", "body": "<p>v1</p>"}])
    await _run(db, snapshot, actor)

    row = await db.scalar(
        select(ConfluenceSnapshotPage).where(
            ConfluenceSnapshotPage.snapshot_id == snapshot.id
        )
    )
    row.body = "<p>v2 rewritten</p>"
    row.title = "One, renamed"
    await db.flush()

    second = await _run(db, snapshot, actor)

    pages = await _pages_in(db, snapshot)
    assert len(pages) == 1, "a second run must not fork the page"
    assert pages[0].title == "One, renamed"
    assert "v2 rewritten" in pages[0].body
    assert second.counts.get("pages_updated") == 1


# --- restrictions: the failure that must NOT be silent ---


async def test_an_unresolvable_principal_blocks_its_page(db):
    """A wiki import that silently opens a restricted page is a data leak, and it
    is the failure nobody notices — the page looks perfectly fine."""
    actor = await _admin(db)
    snapshot = await _snapshot(db, actor, [
        {"id": "1", "title": "Public"},
        {"id": "2", "title": "Secret", "restrictions": RESTRICTED},
    ])
    run = await _run(db, snapshot, actor)

    titles = {p.title for p in await _pages_in(db, snapshot)}
    assert "Public" in titles
    assert "Secret" not in titles, "it must not be created at all, let alone open"
    assert run.counts.get("pages_blocked") == 1
    problem = next(p for p in run.problems if p["kind"] == "restriction")
    # Addressed back to the control that fixes it.
    assert problem["section"] == "groups"
    assert problem["mapping_key"] == "group:a-group-that-does-not-exist"


async def test_a_fallback_lets_a_restricted_page_import_closed(db):
    """"Map all unknown to Y" — the escape hatch, which still closes the page."""
    actor = await _admin(db)
    from radd.modules.teams.models import Team

    team = Team(name=f"Wiki keepers {uuid.uuid4().hex[:5]}")
    db.add(team)
    await db.flush()

    snapshot = await _snapshot(db, actor, [
        {"id": "2", "title": "Secret", "restrictions": RESTRICTED},
    ])
    run = await _run(db, snapshot, actor, options=PlanOptions(
        unresolved_principal=UnresolvedPrincipal.MAP_TO, unresolved_team_id=team.id,
    ))

    titles = {p.title for p in await _pages_in(db, snapshot)}
    assert "Secret" in titles
    assert run.counts.get("restrictions", 0) >= 1, "imported, but CLOSED"

    from radd.modules.access.models import AccessGrant

    grants = int(await db.scalar(
        select(func.count()).select_from(AccessGrant).where(
            AccessGrant.resource_type == "page",
            AccessGrant.subject_id == team.id,
        )
    ) or 0)
    assert grants >= 1


async def test_restrictions_can_be_turned_off_entirely(db):
    actor = await _admin(db)
    snapshot = await _snapshot(db, actor, [
        {"id": "2", "title": "Secret", "restrictions": RESTRICTED},
    ])
    await _run(db, snapshot, actor, options=PlanOptions(import_restrictions=False))
    assert "Secret" in {p.title for p in await _pages_in(db, snapshot)}


# --- history ---


async def test_history_is_absent_unless_asked_for(db):
    """Off by default: a live page in a real corpus sits at version 206."""
    actor = await _admin(db)
    snapshot = await _snapshot(db, actor, [{
        "id": "1", "title": "One", "version": 3,
        "versions": [
            {"version": 1, "title": "One", "body": "<p>first</p>", "author": "", "when": ""},
            {"version": 2, "title": "One", "body": "<p>second</p>", "author": "", "when": ""},
        ],
    }])
    await _run(db, snapshot, actor)

    from radd.modules.pages.models import PageVersion

    page = (await _pages_in(db, snapshot))[0]
    count = int(await db.scalar(
        select(func.count()).select_from(PageVersion).where(PageVersion.page_id == page.id)
    ) or 0)
    assert count == 0


async def test_history_imports_revisions_below_the_live_body(db):
    """`PageVersion` holds the PREVIOUS content, so the live body is revision N and
    history is 1..N-1. Getting it backwards duplicates the current body into the
    History tab and loses revision 1."""
    actor = await _admin(db)
    snapshot = await _snapshot(db, actor, [{
        "id": "1", "title": "One", "version": 3, "body": "<p>live</p>",
        "versions": [
            {"version": 1, "title": "One", "body": "<p>first</p>", "author": "", "when": ""},
            {"version": 2, "title": "One", "body": "<p>second</p>", "author": "", "when": ""},
        ],
    }])
    snapshot.include_history = True
    await db.flush()
    await _run(db, snapshot, actor, options=PlanOptions(include_history=True))

    from radd.modules.pages.models import PageVersion

    page = (await _pages_in(db, snapshot))[0]
    versions = list((await db.execute(
        select(PageVersion).where(PageVersion.page_id == page.id).order_by(PageVersion.version)
    )).scalars())
    assert [v.version for v in versions] == [1, 2]
    assert "first" in versions[0].body
    assert "live" in page.body, "the live body is the newest revision, not a version row"


# --- the wire constant that had no compiler behind it ---


def test_the_attachment_url_matches_a_real_route():
    """The importer writes attachment URLs into page bodies. They must name a
    route the app actually serves.

    It emitted `/attachments/{id}/download`, which does not exist. Everything
    type-checked, the page rendered a `<video>` with controls, and the player
    reported SRC_NOT_SUPPORTED — because its source was a 404 page. Nothing but
    asking the running app catches that.
    """
    import uuid as _uuid

    from radd.app import create_app
    from radd.modules.confluenceimport.runs import _attachment_url

    def walk(routes):
        for route in routes:
            candidates = getattr(route, "effective_candidates", None)
            if candidates is not None:
                yield from walk(candidates())
            elif getattr(route, "path", None):
                yield route.path

    emitted = _attachment_url(_uuid.uuid4())
    # `/api/v1/attachments/<uuid>` -> the template the router registered.
    template = emitted.rsplit("/", 1)[0] + "/{attachment_id}"
    assert template in set(walk(create_app().routes)), (
        f"the importer emits {emitted}, which no route serves"
    )


async def test_unknown_comment_author_imports_and_reads_without_false_attribution(db):
    from radd.modules.confluenceimport.models.snapshot import ConfluenceSnapshotComment
    from radd.modules.comments import service as comments
    actor = await _admin(db)
    snapshot = await _snapshot(db, actor, [{'id':'1', 'title':'Unknown comments'}])
    row = await db.scalar(select(ConfluenceSnapshotPage).where(ConfluenceSnapshotPage.snapshot_id == snapshot.id))
    snapshot.include_comments = True
    db.add(ConfluenceSnapshotComment(snapshot_id=snapshot.id, comment_id='missing-author',
        page_id=row.page_id, body='<p>Unattributed history</p>', author='',
        created_at='2018-04-25T05:46:56Z'))
    await db.flush()
    run = await _run(db, snapshot, actor)
    assert run.counts.get('comments') == 1
    page = (await _pages_in(db, snapshot))[0]
    rows = await comments.list_comments(db, page.id, actor, entity_type='page')
    assert len(rows) == 1 and rows[0].author is None
    assert rows[0].body.strip() == 'Unattributed history'
    assert rows[0].created_at.year == 2018


async def test_ignored_people_never_resolve_by_id_email_domain_or_name(db):
    from radd.modules.confluenceimport.schemas import PlanMappings, UserMapping
    from radd.modules.confluenceimport.types import UserAction
    actor = await _admin(db)
    actor.name = f"Unique ignored {uuid.uuid4()}"
    await db.flush()
    username, domain = actor.email.split("@")
    entries = [
        UserMapping(username="explicit", user_id=actor.id),
        UserMapping(username="email", email=actor.email),
        UserMapping(username=username),
        UserMapping(username="display", display_name=actor.name),
    ]
    assert set((await runs._people(db, PlanMappings(users=entries), email_domain=domain)).values()) == {actor.id}
    for entry in entries:
        entry.action = UserAction.IGNORE
    assert await runs._people(db, PlanMappings(users=entries), email_domain=domain) == {}


async def test_ignored_comment_author_stays_unattributed_in_real_run(db):
    from radd.modules.confluenceimport.models.snapshot import ConfluenceSnapshotComment
    from radd.modules.confluenceimport.schemas import UserMapping
    from radd.modules.confluenceimport.types import UserAction
    from radd.modules.comments import service as comments
    actor = await _admin(db)
    source_author = await _admin(db)
    snapshot = await _snapshot(db, actor, [{'id':'1', 'title':'Ignored author'}])
    row = await db.scalar(select(ConfluenceSnapshotPage).where(ConfluenceSnapshotPage.snapshot_id == snapshot.id))
    db.add(ConfluenceSnapshotComment(snapshot_id=snapshot.id, comment_id='ignored-author',
        page_id=row.page_id, body='<p>Historical comment</p>', author='old-account',
        created_at='2018-04-25T05:46:56Z'))
    plan = await plan_service.create_plan(db, PlanCreate(name='Ignored author', snapshot_id=snapshot.id))
    mappings = plan_service.mappings_of(plan)
    mappings.users = [UserMapping(username='old-account', email=source_author.email,
        user_id=source_author.id, action=UserAction.IGNORE)]
    plan.mappings = mappings.model_dump(mode='json')
    plan.options = PlanOptions(import_comments=True).model_dump(mode='json')
    await db.flush()
    run = await runs.start_run(db, plan.id, dry_run=False, actor_id=actor.id)
    await runs._pipeline(db, run)
    page = (await _pages_in(db, snapshot))[0]
    imported = await comments.list_comments(db, page.id, actor, entity_type='page')
    assert len(imported) == 1
    assert imported[0].author is None
