"""AD user import against accounts that already exist (spec 88).

The classification is pure, so most of this needs no DB. The two write verbs do,
and what they must guarantee is the same thing stated two ways: after either one,
the person has ONE account carrying the directory's identity — and nothing they
ever wrote got orphaned.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import ConflictError
from radd.modules.auth import service as auth_service
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole, UserSource
from radd.modules.ldap import userimport
from radd.modules.ldap.types import (
    DirectoryUser,
    ImportMatchKind,
    ImportResolution,
    ImportStatus,
)


def _dir_user(username, email, name) -> DirectoryUser:
    return DirectoryUser(username=username, email=email, name=name, is_admin=False)


class _Row:
    """The slice of a user row the pure planner reads."""

    def __init__(self, email, name, source=UserSource.LOCAL, active=True):
        self.id = uuid.uuid4()
        self.email = email
        self.name = name
        self.source = source
        self.active = active


# --- the pure planner ---


def test_new_user_has_no_matches():
    [candidate] = userimport.plan_user_import(
        [_dir_user("jsmith", "jsmith@corp.example", "Jane Smith")], []
    )
    assert candidate.status is ImportStatus.NEW
    assert candidate.suggested is ImportResolution.CREATE
    assert candidate.matches == ()


def test_exact_email_is_linked_not_a_conflict():
    existing = _Row("jsmith@corp.example", "J. Smith")
    [candidate] = userimport.plan_user_import(
        [_dir_user("jsmith", "jsmith@corp.example", "Jane Smith")], [existing]
    )
    assert candidate.status is ImportStatus.LINKED
    # Overwrite refreshes the drifted display name from AD.
    assert candidate.suggested is ImportResolution.OVERWRITE
    assert [m.kind for m in candidate.matches] == [ImportMatchKind.EMAIL]


def test_username_matching_an_old_domain_is_a_conflict():
    """The case that silently forked accounts before spec 88: same person, older
    email address, so nothing matched and a second account got created."""
    legacy = _Row("jsmith@old-domain.example", "Jane Smith")
    [candidate] = userimport.plan_user_import(
        [_dir_user("jsmith", "jsmith@corp.example", "Jane Smith")], [legacy]
    )
    assert candidate.status is ImportStatus.CONFLICT
    # One account only -> adopt AD's identity onto it and keep its id.
    assert candidate.suggested is ImportResolution.OVERWRITE
    assert [m.kind for m in candidate.matches] == [ImportMatchKind.USERNAME]


def test_conflict_alongside_an_exact_match_suggests_merge():
    """Both accounts already exist — only a merge ends with one person."""
    current = _Row("jsmith@corp.example", "Jane Smith", source=UserSource.LDAP)
    legacy = _Row("jsmith@old-domain.example", "Jane Smith")
    [candidate] = userimport.plan_user_import(
        [_dir_user("jsmith", "jsmith@corp.example", "Jane Smith")], [current, legacy]
    )
    assert candidate.status is ImportStatus.CONFLICT
    assert candidate.suggested is ImportResolution.MERGE
    kinds = {m.kind for m in candidate.matches}
    assert kinds == {ImportMatchKind.EMAIL, ImportMatchKind.USERNAME}
    # The exact account is reported first — it is the one that survives.
    assert candidate.matches[0].kind is ImportMatchKind.EMAIL


def test_name_only_match_is_reported_but_never_auto_applied():
    """Two people really can share a name, so this is surfaced as a conflict for
    a human to judge — the planner never resolves it on its own."""
    namesake = _Row("j.smith.2@corp.example", "Jane Smith")
    [candidate] = userimport.plan_user_import(
        [_dir_user("jsmith", "jsmith@corp.example", "Jane Smith")], [namesake]
    )
    assert candidate.status is ImportStatus.CONFLICT
    assert [m.kind for m in candidate.matches] == [ImportMatchKind.NAME]


def test_an_account_is_reported_once_under_its_strongest_match():
    existing = _Row("jsmith@corp.example", "Jane Smith")  # matches email, username AND name
    [candidate] = userimport.plan_user_import(
        [_dir_user("jsmith", "jsmith@corp.example", "Jane Smith")], [existing]
    )
    assert len(candidate.matches) == 1 and candidate.matches[0].kind is ImportMatchKind.EMAIL


# --- the write verbs (DB-backed) ---


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _user(db, email, name, *, source=UserSource.LOCAL) -> User:
    user = User(
        email=email, name=name, source=source, instance_role=InstanceRole.MEMBER.value
    )
    db.add(user)
    await db.flush()
    return user


async def test_overwrite_adopts_ad_identity_and_keeps_the_id(db):
    suffix = uuid.uuid4().hex[:6]
    legacy = await _user(db, f"jsmith-{suffix}@old.example", "J Smith")
    original_id = legacy.id
    directory = _dir_user(f"jsmith-{suffix}", f"jsmith-{suffix}@corp.example", "Jane Smith")

    user, created = await userimport.apply_resolution(
        db, directory, ImportResolution.OVERWRITE, legacy.id
    )

    assert created is False
    # Same row: everything this person ever wrote is still theirs.
    assert user.id == original_id
    assert user.email == directory.email
    assert user.name == "Jane Smith"
    assert user.source == UserSource.LDAP  # now directory-governed


async def test_overwrite_refuses_to_steal_an_email_from_another_account(db):
    suffix = uuid.uuid4().hex[:6]
    legacy = await _user(db, f"jsmith-{suffix}@old.example", "J Smith")
    await _user(db, f"jsmith-{suffix}@corp.example", "Jane Smith", source=UserSource.LDAP)
    directory = _dir_user(f"jsmith-{suffix}", f"jsmith-{suffix}@corp.example", "Jane Smith")

    # Two accounts exist; overwriting would collide on the unique email. The 409
    # names the alternative rather than letting the DB raise.
    with pytest.raises(ConflictError, match="merge them instead"):
        await userimport.apply_resolution(db, directory, ImportResolution.OVERWRITE, legacy.id)


async def test_merge_folds_the_lookalike_into_the_directory_account(db):
    suffix = uuid.uuid4().hex[:6]
    current = await _user(db, f"jsmith-{suffix}@corp.example", "Jane S", source=UserSource.LDAP)
    legacy = await _user(db, f"jsmith-{suffix}@old.example", "Jane Smith")
    directory = _dir_user(f"jsmith-{suffix}", f"jsmith-{suffix}@corp.example", "Jane Smith")

    user, created = await userimport.apply_resolution(
        db, directory, ImportResolution.MERGE, legacy.id
    )

    assert created is False
    assert user.id == current.id  # the AD-identified account survives…
    assert user.name == "Jane Smith"  # …carrying AD's values
    #: the look-alike is DELETED, not deactivated. Everything it owned
    # moved to the survivor, so the row held nothing — and a dead duplicate of the
    # same person in every picker was the reason merging felt unfinished.
    assert await auth_service.get_user_by_email(db, legacy.email) is None


async def test_merge_into_itself_is_refused(db):
    suffix = uuid.uuid4().hex[:6]
    current = await _user(db, f"jsmith-{suffix}@corp.example", "Jane Smith", source=UserSource.LDAP)
    directory = _dir_user(f"jsmith-{suffix}", f"jsmith-{suffix}@corp.example", "Jane Smith")

    with pytest.raises(ConflictError, match="nothing to merge"):
        await userimport.apply_resolution(db, directory, ImportResolution.MERGE, current.id)


async def test_skip_writes_nothing_and_create_still_links_by_email(db):
    suffix = uuid.uuid4().hex[:6]
    legacy = await _user(db, f"jsmith-{suffix}@old.example", "Jane Smith")
    directory = _dir_user(f"jsmith-{suffix}", f"jsmith-{suffix}@corp.example", "Jane Smith")

    user, created = await userimport.apply_resolution(db, directory, ImportResolution.SKIP, None)
    assert (user, created) == (None, False)
    await db.refresh(legacy)
    assert legacy.email == f"jsmith-{suffix}@old.example"  # untouched

    # CREATE deliberately keeps the look-alike and makes the separate account.
    user, created = await userimport.apply_resolution(db, directory, ImportResolution.CREATE, None)
    assert created is True and user.id != legacy.id
    assert user.source == UserSource.LDAP


async def test_overwrite_and_merge_require_a_target(db):
    directory = _dir_user("jsmith", "jsmith@corp.example", "Jane Smith")
    for resolution in (ImportResolution.OVERWRITE, ImportResolution.MERGE):
        with pytest.raises(ConflictError, match="needs the account"):
            await userimport.apply_resolution(db, directory, resolution, None)


async def test_planner_sees_the_real_roster(db):
    """End-to-end shape: the planner runs against actual rows, not fixtures."""
    suffix = uuid.uuid4().hex[:6]
    legacy = await _user(db, f"pkumar-{suffix}@old.example", f"Priya Kumar {suffix}")
    directory = _dir_user(f"pkumar-{suffix}", f"pkumar-{suffix}@corp.example", f"Priya Kumar {suffix}")

    candidates = userimport.plan_user_import([directory], await auth_service.list_users(db))
    [candidate] = [c for c in candidates if c.email == directory.email]
    assert candidate.status is ImportStatus.CONFLICT
    assert legacy.id in {m.user_id for m in candidate.matches}
