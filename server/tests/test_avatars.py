"""RADD-1295 — people have pictures.

The rule (upload, else the IdP's, else none) lives in one property; uploads are
normalised so no chip ever downloads a photo; replacing one removes the old
bytes; and a provider can only ever hand the SPA an https URL.
"""

import io
import uuid

import httpx
import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.app import create_app
from radd.config import settings
from radd.db import get_session
from radd.modules.auth import service as auth_service
from radd.modules.auth.models import User
from radd.modules.auth.types import SESSION_COOKIE_NAME, LoginMethod
from radd.modules.avatars.service import AVATAR_PIXELS, normalise


def _png(width: int, height: int, colour=(200, 40, 40)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(out, format="PNG")
    return out.getvalue()


def test_normalise_makes_a_small_square_webp():
    picture = Image.open(io.BytesIO(normalise(_png(1200, 500))))
    assert picture.format == "WEBP"
    assert picture.size == (AVATAR_PIXELS, AVATAR_PIXELS)


def test_normalise_refuses_what_is_not_an_image():
    with pytest.raises(ValueError):
        normalise(b"<svg onload=alert(1)>")


def test_the_one_rule_for_a_picture():
    person = User(id=uuid.uuid4(), email="p@example.com", name="P")
    assert person.avatar_url is None
    person.avatar_idp_url = "https://lh3.example.com/me.jpg"
    assert person.avatar_url == "https://lh3.example.com/me.jpg"
    person.avatar_blob = "0123456789abcdef"
    assert person.avatar_url == f"/api/v1/users/{person.id}/avatar?v=0123456789ab"


@pytest.fixture
async def world(tmp_path):
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        from radd.modules.attachments.models import StorageHost
        from radd.modules.attachments.types import StorageHostType

        if await db.scalar(select(StorageHost).where(StorageHost.is_default)) is None:
            db.add(StorageHost(
                name=f"avatar-test-{uuid.uuid4().hex[:6]}",
                host_type=StorageHostType.FILESYSTEM.value,
                root_dir=str(tmp_path),
                is_default=True,
            ))
        person = User(email=f"av-{uuid.uuid4().hex[:8]}@example.com", name="Pictured", instance_role="member")
        db.add(person)
        await db.flush()
        app = create_app()

        async def override():
            yield db

        app.dependency_overrides[get_session] = override
        token = await auth_service.create_session(db, person, method=LoginMethod.PASSWORD_TOTP)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test/api/v1",
            cookies={SESSION_COOKIE_NAME: token},
        ) as client:
            yield db, client, person
        await db.rollback()
    await engine.dispose()


async def test_upload_replace_serve_and_remove(world):
    db, client, person = world
    first = await client.put("/auth/me/avatar", files={"file": ("me.png", _png(900, 900), "image/png")})
    assert first.status_code == 200, first.text
    url = first.json()["avatar_url"]
    assert url.startswith(f"/api/v1/users/{person.id}/avatar?v=")
    first_blob = person.avatar_blob

    served = await client.get(url.removeprefix("/api/v1"))
    assert served.status_code == 200 and served.headers["content-type"] == "image/webp"
    assert Image.open(io.BytesIO(served.content)).size == (AVATAR_PIXELS, AVATAR_PIXELS)
    assert "immutable" in served.headers["cache-control"]

    second = await client.put("/auth/me/avatar", files={"file": ("me.png", _png(300, 300, (0, 0, 255)), "image/png")})
    assert second.json()["avatar_url"] != url  # a new version, a new URL
    assert person.avatar_blob != first_blob

    person.avatar_idp_url = "https://lh3.example.com/me.jpg"
    removed = await client.delete("/auth/me/avatar")
    assert removed.json()["avatar_url"] == "https://lh3.example.com/me.jpg"  # falls back to the IdP's
    gone = await client.get(f"/users/{person.id}/avatar")
    assert gone.status_code == 404


async def test_refuses_non_images_and_the_wrong_type(world):
    _db, client, _person = world
    fake = await client.put("/auth/me/avatar", files={"file": ("me.png", b"not really", "image/png")})
    assert fake.status_code == 422
    svg = await client.put("/auth/me/avatar", files={"file": ("me.svg", b"<svg/>", "image/svg+xml")})
    assert svg.status_code == 415


async def test_only_https_idp_pictures_are_kept(world):
    db, _client, person = world
    await auth_service.set_idp_picture(db, person, "javascript:alert(1)")
    assert person.avatar_idp_url is None
    await auth_service.set_idp_picture(db, person, "https://avatars.githubusercontent.com/u/1")
    assert person.avatar_url == "https://avatars.githubusercontent.com/u/1"
