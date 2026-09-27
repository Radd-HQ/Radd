"""Attachments staged before the item exists (RADD-800). The staging area is the new
attack surface — an unprivileged person writes to it and the files later move onto
a real issue — so two properties are asserted:

  - the area's id is DERIVED from the caller, so it cannot be handed in;
  - a submission claims only attachments on its OWN caller's area.
"""

import uuid

import pytest

from radd.exceptions import ConflictError
from radd.modules.attachments.models import Attachment
from radd.modules.attachments.types import AttachmentParentType
from radd.modules.auth.models import User
from radd.modules.forms import staging

from _factories import make_user


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
    alice, bob = await make_user(db, name="Alice"), await make_user(db, name="Bob")
    assert staging.staging_id_for(alice) == staging.staging_id_for(alice)
    assert staging.staging_id_for(alice) != staging.staging_id_for(bob)


async def test_you_cannot_reach_someone_elses_staging_area(db):
    alice, bob = await make_user(db, name="Alice"), await make_user(db, name="Bob")
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
    alice = await make_user(db, name="Alice")
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
    alice, bob = await make_user(db, name="Alice"), await make_user(db, name="Bob")
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
    alice = await make_user(db, name="Alice")
    assert await staging.claim(db, alice, uuid.uuid4(), [uuid.uuid4()]) == 0


async def test_only_the_named_files_move(db, host):
    """One staging area per person means a second tab's uploads sit alongside
    this submission's. Naming them is what keeps the tabs apart."""
    alice = await make_user(db, name="Alice")
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

    alice = await make_user(db, name="Alice")
    stale = await _staged(db, host, alice, "last-month.png")
    stale.created_at = datetime.utcnow() - timedelta(days=30)
    await db.flush()

    assert staging.staging_id_for(alice) in await staging.sweep_abandoned(db, older_than_days=7)


async def test_a_recently_used_area_is_left_alone(db, host):
    """Somebody mid-submission must not lose the screenshot they just pasted, so
    an area is judged by its NEWEST file, not its oldest."""
    from datetime import datetime, timedelta

    alice = await make_user(db, name="Alice")
    old = await _staged(db, host, alice, "from-last-month.png")
    old.created_at = datetime.utcnow() - timedelta(days=30)
    await _staged(db, host, alice, "pasted-just-now.png")
    await db.flush()

    assert staging.staging_id_for(alice) not in await staging.sweep_abandoned(db, older_than_days=7)


async def test_the_scheduled_sweep_reclaims_an_abandoned_area_with_its_bytes(
    db, tmp_path, monkeypatch
):
    """RADD-1426: `sweep_abandoned` promised to emit `form.staging.deleted` but
    returned ids, and nothing ever called it, so every abandoned screenshot stayed
    on its storage host forever. Driven end to end: the plugin's scheduled task,
    then the real cascade consumer — rows AND bytes of the abandoned area go, a
    live area keeps both."""
    import io
    from contextlib import asynccontextmanager
    from datetime import timedelta
    from pathlib import Path

    from fastapi import UploadFile

    from radd.clock import utcnow
    from radd.kernel.registry import registries
    from radd.modules.attachments import gc, hosts, service as attachments_service
    from radd.modules.attachments.schemas import StorageHostCreate
    from radd.modules.attachments.types import DeliveryMode, StorageHostType
    from radd.modules.events import cascade, runner, service as events_service

    store = await hosts.create_host(
        db,
        StorageHostCreate(
            name=f"stage-{uuid.uuid4().hex[:6]}",
            host_type=StorageHostType.FILESYSTEM,
            root_dir=str(tmp_path / "store"),
            delivery_mode=DeliveryMode.PROXY,
        ),
    )

    async def upload(owner: User, name: str) -> Attachment:
        return await attachments_service.save_upload(
            db,
            entity_type=AttachmentParentType.FORM_SUBMISSION.value,
            entity_id=staging.staging_id_for(owner),
            upload=UploadFile(file=io.BytesIO(b"png-bytes"), filename=name),
            actor_id=owner.id,
            host=store,
        )

    alice, bob = await make_user(db, name="Alice"), await make_user(db, name="Bob")
    abandoned, live = await upload(alice, "closed-the-tab.png"), await upload(bob, "typing.png")
    abandoned.created_at = utcnow() - timedelta(days=30)
    await db.flush()
    abandoned_id, abandoned_bytes = abandoned.id, Path(store.root_dir) / abandoned.storage_name
    live_bytes = Path(store.root_dir) / live.storage_name
    assert abandoned_bytes.exists() and live_bytes.exists()

    # Every step opens its own session; hand each the test transaction instead.
    @asynccontextmanager
    async def borrowed():
        yield db

    for module in (staging, runner, gc):
        monkeypatch.setattr(module, "SessionLocal", borrowed)
    monkeypatch.setattr(db, "commit", db.flush)
    await events_service.set_offset(
        db, cascade.CONSUMER_NAME, await events_service.latest_event_id(db)
    )

    assert await registries.tasks["forms.staging-sweep"].run() >= 1
    assert await cascade.run_once() >= 1

    assert await db.get(Attachment, abandoned_id) is None
    assert not abandoned_bytes.exists()
    await db.refresh(live)
    assert live.entity_id == staging.staging_id_for(bob)
    assert live_bytes.read_bytes() == b"png-bytes"
