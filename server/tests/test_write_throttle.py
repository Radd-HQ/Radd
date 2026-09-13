"""The per-account write throttle (spec 121 §9, RADD-1148): pure unit tests
over an injected clock, the login throttle's idiom."""

import uuid

import pytest
from fastapi import HTTPException

from radd.config import settings
from radd.modules.auth import throttle
from radd.modules.auth.models import User
from radd.modules.auth.throttle import WriteBucket, WriteThrottle, check_write
from radd.modules.auth.types import InstanceRole


@pytest.fixture
def tight(monkeypatch):
    monkeypatch.setattr(settings, "write_window_seconds", 10)
    monkeypatch.setattr(settings, "item_creates_per_window", 2)
    monkeypatch.setattr(settings, "comments_per_window", 3)
    monkeypatch.setattr(settings, "write_throttle_bucket_limit", 4)


def _refused(limiter: WriteThrottle, bucket: WriteBucket, who: uuid.UUID, now: float) -> int:
    with pytest.raises(HTTPException) as denied:
        limiter.check(bucket, who, now=now)
    assert denied.value.status_code == 429
    return int(denied.value.headers["Retry-After"])


def test_the_n_plus_first_create_in_the_window_is_refused(tight):
    limiter = WriteThrottle()
    alice = uuid.uuid4()
    limiter.check(WriteBucket.ITEM_CREATE, alice, now=0)
    limiter.check(WriteBucket.ITEM_CREATE, alice, now=1)
    # Retry-After counts from the OLDEST entry: it expires at 0 + 10, so 8s from now=2.
    assert _refused(limiter, WriteBucket.ITEM_CREATE, alice, now=2) == 8
    # A refusal records nothing, so the wait never grows with the retries.
    assert _refused(limiter, WriteBucket.ITEM_CREATE, alice, now=3) == 7


def test_accounts_and_buckets_are_independent(tight):
    limiter = WriteThrottle()
    alice, bob = uuid.uuid4(), uuid.uuid4()
    for t in range(2):
        limiter.check(WriteBucket.ITEM_CREATE, alice, now=t)
    _refused(limiter, WriteBucket.ITEM_CREATE, alice, now=2)
    # Another account has its own window …
    limiter.check(WriteBucket.ITEM_CREATE, bob, now=2)
    # … and so does another bucket for the same account (comments allow 3).
    for t in range(3):
        limiter.check(WriteBucket.COMMENT_CREATE, alice, now=2 + t)
    _refused(limiter, WriteBucket.COMMENT_CREATE, alice, now=5)


def test_the_window_slides(tight):
    limiter = WriteThrottle()
    alice = uuid.uuid4()
    limiter.check(WriteBucket.ITEM_CREATE, alice, now=0)
    limiter.check(WriteBucket.ITEM_CREATE, alice, now=5)
    _refused(limiter, WriteBucket.ITEM_CREATE, alice, now=9)
    # now=11: the entry at 0 has aged out of the 10s window; the one at 5 has not.
    limiter.check(WriteBucket.ITEM_CREATE, alice, now=11)
    _refused(limiter, WriteBucket.ITEM_CREATE, alice, now=12)


def test_retained_buckets_are_bounded(tight):
    limiter = WriteThrottle()
    for _ in range(4):
        limiter.check(WriteBucket.ITEM_CREATE, uuid.uuid4(), now=0)
    # A fifth distinct account would exceed the bucket limit: refused for a full window.
    assert _refused(limiter, WriteBucket.ITEM_CREATE, uuid.uuid4(), now=1) == 10
    assert len(limiter.buckets) <= 4
    # Once the window passes, the table empties and admission resumes.
    limiter.check(WriteBucket.ITEM_CREATE, uuid.uuid4(), now=11)
    assert len(limiter.buckets) == 1


def _user(role: InstanceRole, user_id: uuid.UUID | None = None) -> User:
    # `active` is explicit: the column default lands at flush, and an unflushed
    # User reads None — which `is_instance_admin` treats as NOT admin.
    return User(
        id=user_id or uuid.uuid4(),
        email=f"{uuid.uuid4()}@example.com",
        name="Writer",
        instance_role=role,
        active=True,
    )


def test_check_write_exempts_admins_and_the_automation_actor(tight, monkeypatch):
    limiter = WriteThrottle()
    monkeypatch.setattr(throttle, "write_throttle", limiter)
    member = _user(InstanceRole.MEMBER)
    admin = _user(InstanceRole.ADMIN)
    system = _user(InstanceRole.MEMBER, throttle.SYSTEM_ACTOR_ID)
    for _ in range(5):
        check_write(admin, WriteBucket.ITEM_CREATE)
        check_write(system, WriteBucket.ITEM_CREATE)
    assert not limiter.buckets, "exempt actors are not even counted"
    check_write(member, WriteBucket.ITEM_CREATE)
    check_write(member, WriteBucket.ITEM_CREATE)
    with pytest.raises(HTTPException) as denied:
        check_write(member, WriteBucket.ITEM_CREATE)
    assert denied.value.status_code == 429
    assert int(denied.value.headers["Retry-After"]) >= 1


def test_a_scoped_admin_key_without_global_manage_is_not_exempt(tight, monkeypatch):
    """`is_instance_admin` is credential-aware: a spec-113 scoped key on an
    admin account that does not carry `global.manage` is an ordinary writer."""
    from radd.modules.auth.types import Permission

    class Scope:
        def allowed(self, project_id):
            return {Permission.ITEM_CREATE}

    limiter = WriteThrottle()
    monkeypatch.setattr(throttle, "write_throttle", limiter)
    admin = _user(InstanceRole.ADMIN)
    admin.token_scope = Scope()
    check_write(admin, WriteBucket.ITEM_CREATE)
    assert len(limiter.buckets) == 1


def test_the_system_actor_literal_matches_automations():
    """auth loads before automations, so the uuid is a literal — this pin is
    what makes that safe (the notify idiom, `test_notify.py`)."""
    from radd.modules.automations.types import SYSTEM_ACTOR_ID

    assert throttle.SYSTEM_ACTOR_ID == SYSTEM_ACTOR_ID
