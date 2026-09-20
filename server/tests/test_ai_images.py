"""RADD-1275: a summary may show a vision model the entity's pictures.

The pure rule (which attachments qualify, in what order, how many), the wire
shapes for many pictures, the role choice, and the wired path over a
MockTransport: with pictures the vision role gets image parts before the text;
without, the payload is the plain string it always was.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.ai import client, images, provider, registry, summarize
from radd.modules.ai.images import ImagePart, pick_images
from radd.modules.ai.schemas import AiProviderCreate, AiRoleAssign
from radd.modules.ai.types import AiRole, AiWireShape


@dataclass
class Row:
    content_type: str
    size_bytes: int
    state: str
    created_at: datetime
    name: str = ""


T0 = datetime(2026, 9, 20, 12, 0, 0)


def _row(name: str, content_type: str = "image/png", size: int = 1000, minutes: int = 0, state: str = "stored") -> Row:
    return Row(content_type, size, state, T0 + timedelta(minutes=minutes), name)


# --- the pure picker ----------------------------------------------------------


def test_pick_images_keeps_only_pictures_a_vision_model_accepts():
    rows = [
        _row("a.png"),
        _row("b.pdf", "application/pdf"),
        _row("c.jpg", "image/jpeg; charset=binary", minutes=1),
        _row("d.svg", "image/svg+xml"),
        _row("e.mp4", "video/mp4"),
    ]
    assert [r.name for r in pick_images(rows, max_images=10, max_bytes=10_000)] == ["c.jpg", "a.png"]


def test_pick_images_newest_first_capped_and_bounded():
    rows = [_row("old.png", minutes=0), _row("mid.png", minutes=5), _row("new.png", minutes=10)]
    assert [r.name for r in pick_images(rows, max_images=2, max_bytes=10_000)] == ["new.png", "mid.png"]
    huge = _row("huge.png", size=10_001, minutes=20)
    assert huge not in pick_images([*rows, huge], max_images=10, max_bytes=10_000)
    pending = _row("pending.png", minutes=30, state="pending")
    assert pending not in pick_images([*rows, pending], max_images=10, max_bytes=10_000)


# --- wire shapes ----------------------------------------------------------------


def test_user_content_parts_puts_pictures_before_the_text_on_both_shapes():
    pictures = [(b"\x89PNG", "image/png"), (b"\xff\xd8", "image/jpeg")]
    openai = provider.user_content_parts(AiWireShape.OPENAI, "TEXT", pictures)
    assert [part["type"] for part in openai] == ["image_url", "image_url", "text"]
    assert openai[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert openai[-1] == {"type": "text", "text": "TEXT"}
    anthropic = provider.user_content_parts(AiWireShape.ANTHROPIC, "TEXT", pictures)
    assert [part["type"] for part in anthropic] == ["image", "image", "text"]
    assert anthropic[1]["source"] == {"type": "base64", "media_type": "image/jpeg", "data": "/9g="}
    # No pictures = the plain string, byte-identical to the text-only world.
    assert provider.user_content_parts(AiWireShape.OPENAI, "TEXT", []) == "TEXT"


def test_with_images_picks_the_vision_role_and_names_the_files():
    assert summarize.with_images("PROMPT", []) == (AiRole.CHAT, "PROMPT")
    role, text = summarize.with_images(
        "PROMPT", [ImagePart(b"x", "image/png", "crash.png"), ImagePart(b"y", "image/jpeg", "board.jpg")]
    )
    assert role is AiRole.VISION
    assert text.startswith("PROMPT\n\n")
    assert "Images attached (2), in order: crash.png, board.jpg" in text


# --- wired ----------------------------------------------------------------------


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def vision_role(db):
    row = await registry.create_provider(
        db,
        AiProviderCreate(
            name=f"mock-{uuid.uuid4().hex[:8]}",
            wire_shape=AiWireShape.OPENAI,
            base_url="http://mock.local/v1",
            default_model="see-1",
        ),
    )
    await registry.set_role(db, AiRole.VISION, AiRoleAssign(provider_id=row.id))
    await registry.set_role(db, AiRole.CHAT, AiRoleAssign(provider_id=row.id))
    return row


@pytest.fixture
def mock_transport():
    state: dict = {}

    def handle(request: httpx.Request) -> httpx.Response:
        state["request"] = request
        return httpx.Response(200, json={"choices": [{"message": {"content": "seen"}}]})

    client.transport = httpx.MockTransport(handle)
    yield state
    client.transport = None


async def test_complete_sends_pictures_as_parts_and_nothing_extra_without(db, vision_role, mock_transport):
    await client.complete(db, AiRole.VISION, "SYS", "USER", images=[(b"\x89PNG", "image/png")])
    body = json.loads(mock_transport["request"].content)
    content = body["messages"][1]["content"]
    assert isinstance(content, list) and [p["type"] for p in content] == ["image_url", "text"]
    assert content[0]["image_url"]["url"] == "data:image/png;base64,iVBORw=="
    assert body["model"] == "see-1"

    await client.complete(db, AiRole.CHAT, "SYS", "USER")
    plain = json.loads(mock_transport["request"].content)
    assert plain["messages"][1]["content"] == "USER"


async def test_entity_images_is_empty_without_a_vision_role(db):
    # No role assigned in this session: the picker never reaches storage.
    parts = await images.entity_images(db, None, "item", uuid.uuid4())  # type: ignore[arg-type]
    assert parts == []
    # An entity type that carries no attachments is empty the same way.
    parts = await images.entity_images(db, None, "release", uuid.uuid4())  # type: ignore[arg-type]
    assert parts == []
