"""Attachments staged before the item exists (RADD-800).

The only genuinely new attack surface in this feature is the staging area, so
that is what most of this file is about: it is a place an unprivileged person can
write to, and the files sitting in it later move onto a real issue.

Two properties keep it honest, and both are asserted:

  - the area's id is DERIVED from the caller, so it cannot be handed in;
  - a submission may only claim attachments sitting on its OWN caller's area,
    so naming somebody else's id drags nothing across.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import ConflictError
from radd.modules.attachments.models import Attachment
from radd.modules.attachments.types import AttachmentParentType
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.forms import staging


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _user(db, name="Requester") -> User:
    user = User(
        email=f"sa-{uuid.uuid4().hex[:8]}@example.com",
        name=name,
        instance_role=InstanceRole.MEMBER.value,
    )
    db.add(user)
    await db.flush()
    return user


@pytest.fixture
async def host(db):
    """A storage host, because `Attachment.storage_host_id` is NOT NULL. Nothing
    here reads bytes — the rows are what these tests are about."""
    from radd.modules.attachments.models import StorageHost
    from radd.modules.attachments.types import StorageHostType

    row = StorageHost(
        name=f"stage-test-{uuid.uuid4().hex[:6]}",
        host_type=StorageHostType.FILESYSTEM.value,
        root_dir="/tmp/radd-staging-test",
    )
    db.add(row)
    await db.flush()
    return row


async def _staged(db, host, owner: User, filename="screenshot.png") -> Attachment:
    """A file sitting on someone's staging area, as an upload would leave it."""
    attachment = Attachment(
        entity_type=AttachmentParentType.FORM_SUBMISSION.value,
        entity_id=staging.staging_id_for(owner),
        filename=filename,
        content_type="image/png",
        size_bytes=1,
        storage_name=uuid.uuid4().hex,
        storage_host_id=host.id,
        created_by=owner.id,
    )
    db.add(attachment)
    await db.flush()
    return attachment


async def test_the_staging_id_is_derived_from_the_person(db):
    """Stable for one person, different for another — which is what lets the
    guard verify it by comparison instead of trusting what it was handed."""
    alice, bob = await _user(db, "Alice"), await _user(db, "Bob")
    assert staging.staging_id_for(alice) == staging.staging_id_for(alice)
    assert staging.staging_id_for(alice) != staging.staging_id_for(bob)


async def test_you_cannot_reach_someone_elses_staging_area(db):
    alice, bob = await _user(db, "Alice"), await _user(db, "Bob")
    binding = __import__(
        "radd.modules.attachments.parents", fromlist=["binding_for"]
    ).binding_for(AttachmentParentType.FORM_SUBMISSION.value)

    # Your own: fine.
    await binding.require_write(db, alice, staging.staging_id_for(alice))
    await binding.require_read(db, alice, staging.staging_id_for(alice))

    # Somebody else's: refused, for read and write alike.
    with pytest.raises(ConflictError):
        await binding.require_write(db, alice, staging.staging_id_for(bob))
    with pytest.raises(ConflictError):
        await binding.require_read(db, alice, staging.staging_id_for(bob))


async def test_claiming_moves_your_own_files_onto_the_item(db, host):
    alice = await _user(db, "Alice")
    one, two = await _staged(db, host, alice, "a.png"), await _staged(db, host, alice, "b.png")
    item_id = uuid.uuid4()

    moved = await staging.claim(db, alice, item_id, [one.id, two.id])
    await db.flush()

    assert moved == 2
    for attachment in (one, two):
        await db.refresh(attachment)
        assert attachment.entity_type == AttachmentParentType.ITEM.value
        assert attachment.entity_id == item_id


async def test_you_cannot_claim_someone_elses_staged_file(db, host):
    """THE check. Without it, naming a stranger's attachment id would drag their
    file onto your issue — and the id is the only thing you would need."""
    alice, bob = await _user(db, "Alice"), await _user(db, "Bob")
    theirs = await _staged(db, host, bob, "private.png")
    item_id = uuid.uuid4()

    moved = await staging.claim(db, alice, item_id, [theirs.id])
    await db.flush()

    assert moved == 0
    await db.refresh(theirs)
    assert theirs.entity_type == AttachmentParentType.FORM_SUBMISSION.value
    assert theirs.entity_id == staging.staging_id_for(bob)


async def test_claiming_an_unknown_id_does_not_fail_the_submission(db):
    """A request must not be lost because a file was already swept or claimed."""
    alice = await _user(db, "Alice")
    assert await staging.claim(db, alice, uuid.uuid4(), [uuid.uuid4()]) == 0


async def test_only_the_named_files_move(db, host):
    """One staging area per person means a second tab's uploads sit alongside
    this submission's. Naming them is what keeps the tabs apart."""
    alice = await _user(db, "Alice")
    claimed = await _staged(db, host, alice, "this-form.png")
    other_tab = await _staged(db, host, alice, "other-form.png")
    item_id = uuid.uuid4()

    assert await staging.claim(db, alice, item_id, [claimed.id]) == 1
    await db.flush()
    await db.refresh(other_tab)
    assert other_tab.entity_type == AttachmentParentType.FORM_SUBMISSION.value


async def test_an_abandoned_staging_area_is_swept(db, host):
    """Every form somebody opened, attached to and closed leaves bytes behind.
    The sweep names whole AREAS, because a parent is the unit the spec-102
    cascade understands — so cleanup needs no code of its own."""
    from datetime import datetime, timedelta

    alice = await _user(db, "Alice")
    stale = await _staged(db, host, alice, "last-month.png")
    stale.created_at = datetime.utcnow() - timedelta(days=30)
    await db.flush()

    assert staging.staging_id_for(alice) in await staging.sweep_abandoned(db, older_than_days=7)


async def test_a_recently_used_area_is_left_alone(db, host):
    """Somebody mid-submission must not lose the screenshot they just pasted, so
    an area is judged by its NEWEST file, not its oldest."""
    from datetime import datetime, timedelta

    alice = await _user(db, "Alice")
    old = await _staged(db, host, alice, "from-last-month.png")
    old.created_at = datetime.utcnow() - timedelta(days=30)
    await _staged(db, host, alice, "pasted-just-now.png")
    await db.flush()

    assert staging.staging_id_for(alice) not in await staging.sweep_abandoned(db, older_than_days=7)
