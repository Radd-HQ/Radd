"""RADD-988: an agent's access to private storage is not an email export grant."""
import io
import uuid
from contextlib import asynccontextmanager

import pytest
from PIL import Image
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd import mailrender, smtp
from radd.config import settings
from radd.modules.access import service as access
from radd.modules.access.types import GrantSubject
from radd.modules.attachments import email_export, hosts
from radd.modules.attachments.models import Attachment
from radd.modules.attachments.schemas import StorageHostCreate, StorageHostRead, StorageHostUpdate
from radd.modules.auth.models import User
from radd.modules.comments import service as comments
from radd.modules.comments.models import Comment
from radd.modules.comments.schemas import CommentCreate
from radd.modules.items import service as items
from radd.modules.items.schemas import ItemCreate
from radd.modules.mailintake import attachments, outbound, transport
from radd.modules.mailintake.models import MailSender
from radd.modules.mailintake.reply import OutboundReply, Recipient
from radd.modules.mailintake.senders.smtp_sender import SmtpSender
from radd.modules.projects import service as projects
from radd.modules.projects.schemas import ProjectCreate


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def world(db, tmp_path):
    suffix = uuid.uuid4().hex[:8]
    actor = User(email=f"images-{suffix}@example.test", name="Agent", instance_role="admin")
    db.add(actor)
    await db.flush()
    project = await projects.create_project(db, ProjectCreate(key=f"MI{suffix.upper()}", name="Images"))
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="Help"), actor)
    general = await hosts.create_host(db, StorageHostCreate(
        name=f"General {suffix}", host_type="filesystem", root_dir=str(tmp_path / "general"),
        email_images_allowed=True,
    ))
    private = await hosts.create_host(db, StorageHostCreate(
        name=f"Private {suffix}", host_type="filesystem", root_dir=str(tmp_path / "private"),
        user_selectable=True,
    ))
    return actor, item, general, private


def png():
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(buffer, "PNG")
    return buffer.getvalue()


async def file(db, item, host, *, data=None, content_type="image/png", **overrides):
    from pathlib import Path
    data = png() if data is None else data
    row = Attachment(
        entity_type="item", entity_id=item.id, filename="screenshot.png",
        content_type=content_type, size_bytes=len(data), storage_name=uuid.uuid4().hex,
        storage_host_id=host.id, state="stored", **overrides,
    )
    db.add(row)
    await db.flush()
    root = Path(host.root_dir)
    root.mkdir(exist_ok=True)
    (root / row.storage_name).write_bytes(data)
    return row


def link(row):
    return f"![private filename](/api/v1/attachments/{row.id}?w=600)"


async def test_opt_in_is_explicit_and_survives_host_updates(db, world):
    _, _, general, private = world
    assert StorageHostRead.model_validate(general).email_images_allowed
    assert not private.email_images_allowed
    await hosts.update_host(db, private.id, StorageHostUpdate(name="Renamed private host"))
    assert not private.email_images_allowed
    await hosts.make_default(db, private)
    assert not private.email_images_allowed, "default/user-selectable is not export permission"
    await hosts.update_host(db, private.id, StorageHostUpdate(email_images_allowed=True))
    assert private.email_images_allowed
    await hosts.update_host(db, private.id, StorageHostUpdate(email_images_allowed=False))
    assert not private.email_images_allowed


async def test_mixed_reply_reads_only_approved_images(db, world, monkeypatch):
    _, item, general, private = world
    allowed = await file(db, item, general)
    blocked = await file(db, item, private)
    original = email_export.client_for
    reads = []

    def approved_only(host):
        reads.append(host.id)
        assert host.id == general.id, "private bytes must never even be read"
        return original(host)

    monkeypatch.setattr(email_export, "client_for", approved_only)
    body, parts = await attachments.prepare(db, item.id, f"Here: {link(allowed)} {link(blocked)}")
    assert len(parts) == 1 and parts[0].data == png()
    assert reads == [general.id]
    assert "[Image attached]" in body and "[Attachment not included]" in body
    assert "private filename" not in body and "/attachments/" not in body


async def test_restricted_other_issue_and_page_files_are_excluded(db, world):
    actor, item, general, _ = world
    restricted = await file(db, item, general)
    await access.add_grant(db, "attachment", str(restricted.id),
                           subject_type=GrantSubject.USER, subject_id=actor.id, access="read")
    foreign = await file(db, item, general)
    foreign.entity_id = uuid.uuid4()
    page = await file(db, item, general)
    page.entity_type = "page"
    await db.flush()
    assert await email_export.images_for_email(db, item.id, [restricted.id, foreign.id, page.id]) == {}


@pytest.mark.parametrize("content_type,data", [
    ("application/pdf", b"%PDF-1.7"), ("image/svg+xml", b"<svg/>"),
    ("image/png", b"<html>not a PNG</html>"), ("image/jpeg", png()),
])
async def test_only_verified_supported_images(db, world, content_type, data):
    _, item, general, _ = world
    row = await file(db, item, general, content_type=content_type, data=data)
    assert await email_export.images_for_email(db, item.id, [row.id]) == {}


async def test_revoke_or_move_before_sending_excludes_image(db, world):
    _, item, general, private = world
    row = await file(db, item, general)
    assert await email_export.images_for_email(db, item.id, [row.id])
    await hosts.update_host(db, general.id, StorageHostUpdate(email_images_allowed=False))
    assert await email_export.images_for_email(db, item.id, [row.id]) == {}
    await hosts.update_host(db, general.id, StorageHostUpdate(email_images_allowed=True))
    row.storage_host_id = private.id
    await db.flush()
    assert await email_export.images_for_email(db, item.id, [row.id]) == {}


async def test_size_count_and_unavailable_files_do_not_drop_reply(db, world, monkeypatch):
    _, item, general, _ = world
    one = await file(db, item, general)
    two = await file(db, item, general)
    monkeypatch.setattr(email_export, "MAX_TOTAL_BYTES", len(png()))
    assert len(await email_export.images_for_email(db, item.id, [one.id, one.id, two.id])) == 1
    monkeypatch.setattr(email_export, "MAX_IMAGE_BYTES", len(png()) - 1)
    assert await email_export.images_for_email(db, item.id, [one.id]) == {}
    monkeypatch.setattr(email_export, "MAX_IMAGE_BYTES", len(png()) + 1)
    one.size_bytes = 1  # storage size is checked independently of the row
    monkeypatch.setattr(email_export, "MAX_TOTAL_BYTES", len(png()) - 1)
    await db.flush()
    assert await email_export.images_for_email(db, item.id, [one.id]) == {}
    monkeypatch.setattr(email_export, "MAX_TOTAL_BYTES", len(png()) * 3)
    monkeypatch.setattr(email_export, "MAX_IMAGES", 1)
    assert len(await email_export.images_for_email(db, item.id, [one.id, two.id])) == 1
    from pathlib import Path
    Path(general.root_dir, one.storage_name).unlink()
    body, parts = await attachments.prepare(db, item.id, "Keep this reply. " + link(one))
    assert "Keep this reply." in body and not parts


async def test_only_same_instance_explicit_references_are_exported(db, world, monkeypatch):
    _, item, general, _ = world
    row = await file(db, item, general)
    monkeypatch.setattr(settings, "app_base_url", "https://radd.example.test")
    path = f"/api/v1/attachments/{row.id}"
    _, parts = await attachments.prepare(db, item.id, f"![x](https://radd.example.test{path})")
    assert len(parts) == 1
    for body in (f"![x](https://other.example.test{path})", path,
                 f"![x](//other.example.test{path})", f"<img src='{path}'>", "No references"):
        assert not (await attachments.prepare(db, item.id, body))[1]


async def test_public_comment_is_rechecked_before_export(db, world):
    actor, item, _, _ = world
    comment = await comments.create_comment(db, item.id, CommentCreate(body="A reply"), actor)
    assert await comments.public_reply_body(db, comment.id, item.id) == "A reply"
    await db.execute(update(Comment).where(Comment.id == comment.id).values(visibility="internal"))
    await db.flush()
    assert await comments.public_reply_body(db, comment.id, item.id) is None
    assert await comments.public_reply_body(db, comment.id, uuid.uuid4()) is None


async def test_real_outbound_path_sends_mime_with_only_allowed_parts(db, world, monkeypatch):
    actor, item, general, private = world
    allowed = await file(db, item, general)
    blocked = await file(db, item, private)
    comment = await comments.create_comment(
        db, item.id, CommentCreate(body=f"See these. {link(allowed)} {link(blocked)}"), actor,
    )
    planned = OutboundReply(item.id, comment.id, "Help", comment.body, actor.name,
                            mailrender.ItemMail("MI-1", "Help", "https://radd.example.test"),
                            (Recipient("customer@example.test"),))
    row = MailSender(name="test", kind="smtp", host="relay.example.test", port=25,
                     from_address="help@example.test", reply_to="help@example.test", secret="",
                     username="", starttls=False)

    async def sender(*args):
        return SmtpSender(row), row

    @asynccontextmanager
    async def session():
        # _deliver owns its transaction; prevent the fixture's data being committed.
        from unittest.mock import AsyncMock
        monkeypatch.setattr(db, "commit", AsyncMock())
        yield db

    sent = []

    class Relay:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def send_message(self, message): sent.append(message)

    monkeypatch.setattr(smtp.smtplib, "SMTP", Relay)
    monkeypatch.setattr(transport, "_sender", sender)
    monkeypatch.setattr(outbound, "SessionLocal", session)
    await outbound._deliver(planned)
    assert len(sent) == 1
    message = sent[0]
    assert message.get_content_type() == "multipart/mixed"
    alternative, part = list(message.iter_parts())
    assert alternative.get_content_type() == "multipart/alternative"
    assert part.get_content_type() == "image/png" and part.get_payload(decode=True) == png()
    assert part.get_filename() == "screenshot.png"
    assert message["Reply-To"] == "help@example.test" and message["Message-ID"]
    for text_part in alternative.iter_parts():
        content = text_part.get_content()
        assert "See these." in content and "Attachment not included" in content
        assert str(blocked.id) not in content and "private filename" not in content
    await db.execute(update(Comment).where(Comment.id == comment.id).values(visibility="internal"))
    await db.flush()
    await outbound._deliver(planned)
    assert len(sent) == 1, "a now-internal comment cannot be sent from a stale plan"
