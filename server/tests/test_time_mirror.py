"""RADD-1258: time logged on a merge/pull request mirrored into worklogs.

The two properties the epic (RADD-1257) is built on — never twice, and removal
follows the source — plus the decisions around them: one target item per ref,
authors matched by email then map then parked (never guessed), mirrored rows
read-only in Radd, disabled projects skipped. Runs against live Postgres inside
a rolled-back transaction.
"""

import uuid
from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import ConflictError
from radd.modules.auth import authz
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemCreate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.timelogging import categories, enablement, external
from radd.modules.timelogging import service as timelog
from radd.modules.timelogging.models import Worklog
from radd.modules.timelogging.schemas import WorklogUpdate
from radd.modules.vcs import timemirror
from radd.modules.vcs.models import VcsPendingWorklog, VcsUserLink
from radd.modules.vcs.types import VcsMatchedBy, VcsProvider

GITLAB = VcsProvider.GITLAB


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _user(db, email: str, name: str) -> User:
    user = User(email=email, name=name, instance_role=InstanceRole.ADMIN.value)
    db.add(user)
    await db.flush()
    return user


@pytest.fixture
async def world(db):
    """An admin, a project with time logging ON, two items, and a category."""
    suffix = uuid.uuid4().hex[:6]
    admin = await _user(db, f"tm-admin-{suffix}@example.com", "Mirror Admin")
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"TM{suffix[:4].upper()}", name="Time mirror")
    )
    await enablement.set_enabled(db, project.id, True, actor_id=admin.id)
    a = await items_service.create_item(db, ItemCreate(project_id=project.id, title="a"), actor=admin)
    b = await items_service.create_item(db, ItemCreate(project_id=project.id, title="b"), actor=admin)
    await categories.ensure_default_categories(db)
    category = (await categories.list_categories(db))[0]
    return {
        "admin": admin,
        "project": project,
        "a": await items_service.require_item(db, a.id),
        "b": await items_service.require_item(db, b.id),
        "a_key": f"{project.key}-{a.number}",
        "b_key": f"{project.key}-{b.number}",
        "category": category,
        "connection": uuid.uuid4(),
    }


def _entry(external_id: str, seconds: int, *, user: str, email: str = "", note: str = "", day: date = date(2026, 9, 18)):
    return timemirror.SourceEntry(
        external_id=external_id,
        seconds=seconds,
        spent_on=day,
        author_username=user,
        author_email=email,
        note=note,
    )


async def _mirrored(db, scope: str) -> dict[str, Worklog]:
    rows = await db.execute(
        select(Worklog).where(Worklog.external_source == GITLAB.value, Worklog.external_scope == scope)
    )
    return {row.external_id: row for row in rows.scalars()}


async def _reconcile(db, world, scope: str, entries, *, texts=None):
    return await timemirror.reconcile(
        db,
        provider=GITLAB,
        connection_id=world["connection"],
        scope=scope,
        ref_texts=texts if texts is not None else [f"feature/{world['a_key']}-thing", "title", ""],
        entries=entries,
        category_id=world["category"].id,
        note_prefix="Logged on !41",
    )


# --- never twice, removal follows the source ---


async def test_reconcile_creates_updates_deletes_and_is_idempotent(db, world):
    admin = world["admin"]
    scope = "pr:group/repo:41"
    first = await _reconcile(
        db, world, scope,
        [_entry("gid://1", 3600, user="hjarrar", email=admin.email), _entry("gid://2", 1800, user="hjarrar", email=admin.email)],
    )
    assert (first.created, first.updated, first.deleted) == (2, 0, 0)
    rows = await _mirrored(db, scope)
    assert {k: r.time_spent_seconds for k, r in rows.items()} == {"gid://1": 3600, "gid://2": 1800}
    assert all(r.author_id == admin.id and r.item_id == world["a"].id for r in rows.values())
    assert rows["gid://1"].note == "Logged on !41"
    assert rows["gid://1"].category_id == world["category"].id

    # The same set again — a re-delivered webhook, a backfill after the hook.
    again = await _reconcile(
        db, world, scope,
        [_entry("gid://1", 3600, user="hjarrar", email=admin.email), _entry("gid://2", 1800, user="hjarrar", email=admin.email)],
    )
    assert (again.created, again.updated, again.deleted, again.unchanged) == (0, 0, 0, 2)
    assert len(await _mirrored(db, scope)) == 2

    # One changed at the source, one removed, one new.
    third = await _reconcile(
        db, world, scope,
        [_entry("gid://1", 7200, user="hjarrar", email=admin.email), _entry("gid://3", 600, user="hjarrar", email=admin.email)],
    )
    assert (third.created, third.updated, third.deleted) == (1, 1, 1)
    rows = await _mirrored(db, scope)
    assert {k: r.time_spent_seconds for k, r in rows.items()} == {"gid://1": 7200, "gid://3": 600}

    # `/remove_time_spent`: the source has nothing left.
    gone = await _reconcile(db, world, scope, [])
    assert gone.deleted == 2
    assert await _mirrored(db, scope) == {}


async def test_deletion_is_scoped_to_the_ref_not_the_item(db, world):
    """Two MRs log time to the same item; reconciling one must not touch the other."""
    admin = world["admin"]
    await _reconcile(db, world, "pr:group/repo:1", [_entry("gid://a", 60, user="hjarrar", email=admin.email)])
    await _reconcile(db, world, "pr:group/repo:2", [_entry("gid://b", 60, user="hjarrar", email=admin.email)])
    report = await _reconcile(db, world, "pr:group/repo:1", [])
    assert report.deleted == 1
    assert await _mirrored(db, "pr:group/repo:1") == {}
    assert list(await _mirrored(db, "pr:group/repo:2")) == ["gid://b"]


async def test_backfill_after_webhook_lands_on_one_row(db, world):
    """The unique index, not the lookup, is the guarantee: a second insert of the
    same external id becomes an update."""
    admin = world["admin"]
    entry = external.ExternalEntry(
        external_id="gid://dup", item_id=world["a"].id, author_id=admin.id,
        seconds=60, worked_on=date(2026, 9, 1), note="x", category_id=None,
    )
    _row, first = await external.upsert_external_worklog(db, source=GITLAB.value, scope="pr:r:1", entry=entry)
    _row, second = await external.upsert_external_worklog(db, source=GITLAB.value, scope="pr:r:1", entry=entry)
    assert (first, second) == ("created", "unchanged")
    count = await db.scalar(
        select(func.count()).select_from(Worklog).where(Worklog.external_id == "gid://dup")
    )
    assert count == 1


# --- which item ---


async def test_target_is_the_first_key_in_order_and_the_note_overrides(db, world):
    admin = world["admin"]
    a, b = world["a"], world["b"]
    a_key, b_key = world["a_key"], world["b_key"]
    report = await timemirror.reconcile(
        db,
        provider=GITLAB,
        connection_id=world["connection"],
        scope="pr:group/repo:9",
        # branch names B, title names A: the branch wins.
        ref_texts=[f"{b_key}-branch", f"{a_key} in the title", None],
        entries=[
            _entry("gid://x", 60, user="hjarrar", email=admin.email),
            _entry("gid://y", 60, user="hjarrar", email=admin.email, note=f"{a_key} review"),
        ],
        category_id=None,
        note_prefix="Logged on !9",
    )
    assert report.created == 2
    rows = await _mirrored(db, "pr:group/repo:9")
    assert rows["gid://x"].item_id == b.id
    assert rows["gid://y"].item_id == a.id  # the entry's own key wins
    assert rows["gid://y"].note == f"{a_key} review"


async def test_no_known_key_anywhere_writes_nothing(db, world):
    admin = world["admin"]
    report = await _reconcile(
        db, world, "pr:group/repo:7",
        [_entry("gid://n", 60, user="hjarrar", email=admin.email)],
        texts=["no-key-branch", "ZZZZ-1 is not a project", ""],
    )
    assert report.no_item == 1 and report.created == 0
    assert await _mirrored(db, "pr:group/repo:7") == {}


# --- who ---


async def test_author_by_email_then_map_then_parked(db, world):
    admin = world["admin"]
    other = await _user(db, f"tm-other-{uuid.uuid4().hex[:6]}@example.com", "Other Person")
    connection = world["connection"]
    scope = "pr:group/repo:3"
    report = await _reconcile(
        db, world, scope,
        [
            _entry("gid://e", 60, user="hjarrar", email=admin.email),   # email match
            _entry("gid://u", 120, user="ghost", email="nobody@example.invalid"),  # nobody
        ],
    )
    assert report.created == 1 and report.pending == 1
    assert report.unmatched_authors == {"ghost"}

    # The email match was RECORDED so the admin can see it.
    links = await timemirror.list_user_links(db, provider=GITLAB, connection_id=connection)
    assert [(link.external_username, link.user_id, link.matched_by) for link in links] == [("hjarrar", admin.id, VcsMatchedBy.EMAIL.value)]

    # The unmatched author is derived from the parked rows; no worklog exists.
    unmatched = await timemirror.list_unmatched(db, provider=GITLAB, connection_id=connection)
    assert [(u.external_username, u.pending_entries, u.pending_seconds) for u in unmatched] == [("ghost", 1, 120)]
    assert "gid://u" not in await _mirrored(db, scope)

    # Map and replay: the parked entry becomes a real worklog, by external id.
    replayed = await timemirror.map_and_replay(
        db, provider=GITLAB, connection_id=connection, username="Ghost", user_id=other.id, actor_id=admin.id,
    )
    assert replayed == 1
    rows = await _mirrored(db, scope)
    assert rows["gid://u"].author_id == other.id and rows["gid://u"].time_spent_seconds == 120
    assert await timemirror.list_unmatched(db, provider=GITLAB, connection_id=connection) == []

    # A later reconcile from the source finds the same row (the map now resolves).
    again = await _reconcile(
        db, world, scope,
        [_entry("gid://e", 60, user="hjarrar", email=admin.email), _entry("gid://u", 120, user="ghost")],
    )
    assert (again.created, again.unchanged, again.pending) == (0, 2, 0)


async def test_parked_entries_follow_the_source_too(db, world):
    connection = world["connection"]
    scope = "pr:group/repo:5"
    await _reconcile(db, world, scope, [_entry("gid://p1", 60, user="ghost"), _entry("gid://p2", 60, user="ghost")])
    await _reconcile(db, world, scope, [_entry("gid://p1", 60, user="ghost")])
    parked = await db.execute(select(VcsPendingWorklog.external_id).where(VcsPendingWorklog.external_scope == scope))
    assert [row for (row,) in parked.all()] == ["gid://p1"]
    await timemirror.forget_connection(db, provider=GITLAB, connection_id=connection)
    left = await db.scalar(select(func.count()).select_from(VcsPendingWorklog).where(VcsPendingWorklog.connection_id == connection))
    assert left == 0


async def test_manual_map_beats_an_earlier_email_match(db, world):
    admin = world["admin"]
    other = await _user(db, f"tm-manual-{uuid.uuid4().hex[:6]}@example.com", "Manual Person")
    connection = world["connection"]
    assert await timemirror.resolve_author(db, provider=GITLAB, connection_id=connection, username="hj", email=admin.email) == admin.id
    await timemirror.set_user_link(db, provider=GITLAB, connection_id=connection, username="HJ", user_id=other.id, actor_id=admin.id)
    assert await timemirror.resolve_author(db, provider=GITLAB, connection_id=connection, username="hj", email=admin.email) == other.id
    links = await timemirror.list_user_links(db, provider=GITLAB, connection_id=connection)
    assert len(links) == 1 and links[0].matched_by == VcsMatchedBy.MANUAL.value
    # Per connection: the same username elsewhere is unknown.
    assert await timemirror.resolve_author(db, provider=GITLAB, connection_id=uuid.uuid4(), username="hj") is None


# --- read-only in Radd, disabled projects ---


async def test_mirrored_rows_refuse_edit_and_delete_for_everyone(db, world):
    admin = world["admin"]
    await _reconcile(db, world, "pr:group/repo:2", [_entry("gid://ro", 60, user="hjarrar", email=admin.email)])
    row = (await _mirrored(db, "pr:group/repo:2"))["gid://ro"]
    with pytest.raises(ConflictError):
        await timelog.authorize_mutation(db, admin, row, others=authz.Permission.PROJECT_MANAGE)
    with pytest.raises(ConflictError):
        await timelog.authorize_mutation(db, admin, row, others=authz.Permission.WORKLOG_DELETE)
    # A hand-logged row by the same admin is still theirs to edit.
    hand = Worklog(item_id=world["a"].id, author_id=admin.id, worked_on=date(2026, 9, 1), time_spent_seconds=60)
    db.add(hand)
    await db.flush()
    await timelog.authorize_mutation(db, admin, hand, others=authz.Permission.PROJECT_MANAGE)
    await timelog.update_worklog(db, hand, WorklogUpdate(time_spent="2h"), admin.id)


async def test_project_with_time_logging_off_receives_nothing(db, world):
    admin = world["admin"]
    await enablement.set_enabled(db, world["project"].id, False, actor_id=admin.id)
    report = await _reconcile(db, world, "pr:group/repo:8", [_entry("gid://off", 60, user="hjarrar", email=admin.email)])
    assert report.skipped_disabled == 1 and report.created == 0
    assert await _mirrored(db, "pr:group/repo:8") == {}


async def test_reads_carry_the_provenance(db, world):
    admin = world["admin"]
    await _reconcile(db, world, "pr:group/repo:4", [_entry("gid://rd", 60, user="hjarrar", email=admin.email)])
    summary = await timelog.item_summary(db, world["a"].id, world["project"])
    entry = next(e for e in summary.entries if e.external_source)
    assert (entry.external_source, entry.external_scope) == (GITLAB.value, "pr:group/repo:4")


async def test_default_category_falls_back_to_development(db, world):
    dev = next(c for c in await categories.list_categories(db) if c.name == "Development")
    assert await timemirror.default_category_id(db, None) == dev.id
    assert await timemirror.default_category_id(db, world["category"].id) == world["category"].id
    assert await timemirror.default_category_id(db, uuid.uuid4()) == dev.id  # a vanished choice


async def test_user_link_rows_are_per_connection_and_lowercased(db, world):
    admin = world["admin"]
    await timemirror.set_user_link(db, provider=GITLAB, connection_id=world["connection"], username="  MixedCase ", user_id=admin.id, actor_id=admin.id)
    row = await db.scalar(select(VcsUserLink).where(VcsUserLink.connection_id == world["connection"]))
    assert row.external_username == "mixedcase"
