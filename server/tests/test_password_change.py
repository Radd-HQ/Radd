"""A local password can be changed and reset (RADD-1529).

`password_hash` was written at user creation and by the seed CLI, and nowhere
else: the seeded admin password stayed whatever was typed on a command line,
and a leaked password could not be rotated without shell access.
"""

import pytest
from sqlalchemy import func, select

from _factories import make_user
from radd.exceptions import ConflictError, ForbiddenError, UnauthorizedError
from radd.modules.auth import passwords, security, service
from radd.modules.auth.models import UserSession
from radd.modules.auth.types import AuthEvent, InstanceRole, LoginMethod, UserSource
from radd.modules.events import service as events

OLD, NEW = "correct horse battery", "staple another phrase"


async def _local(db, **fields):
    return await make_user(
        db, source=UserSource.LOCAL.value, password_hash=security.hash_password(OLD), **fields
    )


async def _sessions(db, user) -> int:
    return await db.scalar(
        select(func.count()).select_from(UserSession).where(UserSession.user_id == user.id)
    )


async def _last(db, head: int, kind: AuthEvent):
    return [e for e in await events.read_after(db, head, 100) if e.event_type == kind]


async def test_a_person_changes_their_own_and_their_other_sessions_end(db):
    user = await _local(db)
    here = await service.create_session(db, user, method=LoginMethod.PASSWORD)
    await service.create_session(db, user, method=LoginMethod.PASSWORD)  # another browser
    head = await events.latest_event_id(db)

    ended = await passwords.change_own(
        db, user, current_password=OLD, new_password=NEW,
        keep_token_hash=security.hash_token(here),
    )

    assert ended == 1 and await _sessions(db, user) == 1, "the session making the change is kept"
    assert security.verify_password(NEW, user.password_hash)
    assert not security.verify_password(OLD, user.password_hash)
    [event] = await _last(db, head, AuthEvent.PASSWORD_CHANGED)
    assert event.actor_id == user.id and event.payload["sessions_ended"] == 1
    assert NEW not in str(event.payload) and user.password_hash not in str(event.payload)


async def test_the_current_password_must_be_right_and_nothing_changes_when_it_is_not(db):
    user = await _local(db)
    await service.create_session(db, user, method=LoginMethod.PASSWORD)
    before = user.password_hash

    with pytest.raises(UnauthorizedError):
        await passwords.change_own(
            db, user, current_password="a wrong guess", new_password=NEW, keep_token_hash=None
        )

    assert user.password_hash == before and await _sessions(db, user) == 1


async def test_the_new_password_cannot_be_the_current_one(db):
    user = await _local(db)
    with pytest.raises(ConflictError):
        await passwords.change_own(
            db, user, current_password=OLD, new_password=OLD, keep_token_hash=None
        )


async def test_an_account_without_a_radd_password_is_refused_on_both_paths(db, admin):
    directory = await make_user(db, source=UserSource.LDAP.value)  # no password_hash
    assert not directory.has_local_password
    with pytest.raises(ConflictError):
        await passwords.change_own(
            db, directory, current_password=OLD, new_password=NEW, keep_token_hash=None
        )
    with pytest.raises(ConflictError):
        await passwords.admin_set(db, admin=admin, target=directory, new_password=NEW)
    assert directory.password_hash is None, "a reset must not GIVE a directory account a password"


async def test_an_admin_reset_signs_the_person_out_everywhere_and_is_audited(db, admin):
    target = await _local(db)
    await service.create_session(db, target, method=LoginMethod.PASSWORD)
    await service.create_session(db, target, method=LoginMethod.PASSWORD)
    head = await events.latest_event_id(db)

    ended = await passwords.admin_set(db, admin=admin, target=target, new_password=NEW)

    assert ended == 2 and await _sessions(db, target) == 0
    assert security.verify_password(NEW, target.password_hash)
    [event] = await _last(db, head, AuthEvent.PASSWORD_RESET)
    assert event.actor_id == admin.id
    assert event.payload["admin"] == admin.email and event.payload["target"] == target.email
    assert NEW not in str(event.payload)


async def test_user_manage_alone_cannot_take_over_an_instance_admin(db):
    """Resetting an admin's password and signing in as them would turn
    `user.manage` into every permission there is."""
    manager = await _local(db)  # a member; the route checks user.manage, the service the rank
    owner = await _local(db, role=InstanceRole.ADMIN)
    before = owner.password_hash

    with pytest.raises(ForbiddenError):
        await passwords.admin_set(db, admin=manager, target=owner, new_password=NEW)

    assert owner.password_hash == before


async def test_an_admin_cannot_skip_the_current_password_on_their_own_account(db):
    owner = await _local(db, role=InstanceRole.ADMIN)
    with pytest.raises(ConflictError):
        await passwords.admin_set(db, admin=owner, target=owner, new_password=NEW)
