"""The attachment MCP tools: the round trip an agent needs (upload a screenshot to an
issue, list it, look at it, move it to a wiki page, delete the original) runs through
the same bindings REST uses, so a read-only principal can list and download but is
refused upload and delete; the inline cap refuses with the REST route named; and a
download is content blocks (an image block for an image), not JSON.
"""

import base64
import uuid

import pytest

from radd.config import settings
from radd.kernel.mcptools import ToolContent, ToolContentType
from radd.exceptions import ForbiddenError
from radd.modules.attachments import hosts, mcptools
from radd.modules.attachments.schemas import StorageHostCreate
from radd.modules.attachments.types import DeliveryMode, StorageHostType
from radd.modules.auth import roles as auth_roles
from radd.modules.auth.models import GlobalRoleGrant
from radd.modules.auth.schemas import RoleCreate
from radd.modules.auth.types import InstanceRole, Permission
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemCreate
from radd.modules.pages import service as pages_service
from radd.modules.pages import spaces as pages_spaces
from radd.modules.pages.schemas import PageCreate, PageSpaceCreate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate

from _factories import make_user

PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(24))


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


@pytest.fixture
async def world(db, tmp_path):
    """(admin, read-only member, item, page) on a tmp filesystem host."""
    admin = await make_user(db, role=InstanceRole.ADMIN, name="MCP files")
    member = await make_user(db, name="MCP reader")
    await hosts.create_host(
        db,
        StorageHostCreate(
            name=f"fs-{uuid.uuid4().hex[:6]}",
            host_type=StorageHostType.FILESYSTEM,
            root_dir=str(tmp_path / "store"),
            delivery_mode=DeliveryMode.PROXY,
            is_default=True,
        ),
    )
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"MF{uuid.uuid4().hex[:4].upper()}", name="MCP files")
    )
    item = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="a screenshot lives here"), actor=admin
    )
    reader = await auth_roles.create_role(
        db,
        RoleCreate(
            key=f"mcpr{uuid.uuid4().hex[:6]}", name="Reader", permissions=[Permission.ITEM_READ]
        ),
    )
    db.add(GlobalRoleGrant(project_id=project.id, user_id=member.id, role_id=reader.id))
    space = await pages_spaces.create_space(
        db, PageSpaceCreate(name=f"S{uuid.uuid4().hex[:6]}"), actor_id=admin.id
    )
    page = await pages_service.create_page(
        db, PageCreate(space_id=space.id, title="Investigation notes"), actor_id=admin.id
    )
    await db.flush()
    return admin, member, item, page


async def test_an_agent_moves_a_screenshot_from_an_issue_to_a_page(db, world):
    admin, _member, item, page = world
    uploaded = await mcptools._upload_attachment(
        db, admin, {"key": item.key, "filename": "shot.png", "content_base64": b64(PNG)}
    )
    assert uploaded["content_type"] == "image/png"  # guessed from the name
    assert uploaded["size_bytes"] == len(PNG)
    assert uploaded["markdown"] == f"![shot.png](/api/v1/attachments/{uploaded['id']})"
    assert uploaded["url"].endswith(f"/api/v1/attachments/{uploaded['id']}")

    listed = await mcptools._list_attachments(db, admin, {"key": item.key})
    assert listed["parent"]["label"] == item.key
    assert [row["id"] for row in listed["attachments"]] == [uploaded["id"]]

    shown = await mcptools._download_attachment(db, admin, {"attachment_id": uploaded["id"]})
    assert isinstance(shown, ToolContent)
    text, image = shown.blocks
    assert text["type"] == ToolContentType.TEXT.value and uploaded["id"] in text["text"]
    assert image["type"] == ToolContentType.IMAGE.value
    assert image["mimeType"] == "image/png"
    assert base64.b64decode(image["data"]) == PNG

    moved = await mcptools._upload_attachment(
        db,
        admin,
        {
            "page_id": str(page.id),
            "filename": "shot.png",
            "content_base64": image["data"],
            "content_type": "image/png",
        },
    )
    on_page = await mcptools._list_attachments(db, admin, {"page_id": str(page.id)})
    assert on_page["parent"]["entity_type"] == "page"
    assert [row["id"] for row in on_page["attachments"]] == [moved["id"]]

    deleted = await mcptools._delete_attachment(db, admin, {"attachment_id": uploaded["id"]})
    assert deleted == {"id": uploaded["id"], "filename": "shot.png", "deleted": True}
    assert (await mcptools._list_attachments(db, admin, {"key": item.key}))["attachments"] == []


async def test_a_non_image_downloads_as_an_embedded_resource(db, world):
    admin, _member, item, _page = world
    uploaded = await mcptools._upload_attachment(
        db,
        admin,
        {"key": item.key, "filename": "trace.log", "content_base64": b64(b"line one\nline two\n")},
    )
    assert uploaded["markdown"].startswith("[trace.log](")
    shown = await mcptools._download_attachment(db, admin, {"attachment_id": uploaded["id"]})
    _text, blob = shown.blocks
    assert blob["type"] == ToolContentType.RESOURCE.value
    assert blob["resource"]["uri"] == uploaded["url"]
    assert base64.b64decode(blob["resource"]["blob"]) == b"line one\nline two\n"


async def test_a_reader_may_list_and_download_but_not_upload_or_delete(db, world):
    admin, member, item, _page = world
    uploaded = await mcptools._upload_attachment(
        db, admin, {"key": item.key, "filename": "shot.png", "content_base64": b64(PNG)}
    )
    listed = await mcptools._list_attachments(db, member, {"key": item.key})
    assert [row["id"] for row in listed["attachments"]] == [uploaded["id"]]
    shown = await mcptools._download_attachment(db, member, {"attachment_id": uploaded["id"]})
    assert shown.blocks[1]["type"] == ToolContentType.IMAGE.value
    with pytest.raises(ForbiddenError):
        await mcptools._upload_attachment(
            db, member, {"key": item.key, "filename": "mine.png", "content_base64": b64(PNG)}
        )
    with pytest.raises(ForbiddenError):
        await mcptools._delete_attachment(db, member, {"attachment_id": uploaded["id"]})
    # the refusal changed nothing
    still = await mcptools._list_attachments(db, admin, {"key": item.key})
    assert [row["id"] for row in still["attachments"]] == [uploaded["id"]]


async def test_the_inline_cap_refuses_both_ways_and_names_the_rest_route(db, world, monkeypatch):
    admin, _member, item, _page = world
    uploaded = await mcptools._upload_attachment(
        db, admin, {"key": item.key, "filename": "big.bin", "content_base64": b64(b"x" * 32)}
    )
    monkeypatch.setattr(settings, "mcp_attachment_max_bytes", 16)
    with pytest.raises(ValueError, match="POST .*/api/v1/attachments"):
        await mcptools._upload_attachment(
            db, admin, {"key": item.key, "filename": "big.bin", "content_base64": b64(b"x" * 17)}
        )
    with pytest.raises(ValueError, match=f"GET .*/api/v1/attachments/{uploaded['id']}"):
        await mcptools._download_attachment(db, admin, {"attachment_id": uploaded["id"]})


async def test_a_parent_is_exactly_one_of_key_or_page_id(db, world):
    admin, _member, item, page = world
    with pytest.raises(ValueError, match="exactly one"):
        await mcptools._list_attachments(db, admin, {})
    with pytest.raises(ValueError, match="exactly one"):
        await mcptools._list_attachments(db, admin, {"key": item.key, "page_id": str(page.id)})
    with pytest.raises(ValueError, match="base64"):
        await mcptools._upload_attachment(
            db, admin, {"key": item.key, "filename": "x.png", "content_base64": "not base64!"}
        )
