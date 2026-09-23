"""RADD-1113: visible, bounded windows must not drift or leak parent discussions."""
import uuid
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import NotFoundError
from radd.modules.auth.models import User
from radd.modules.auth.scopes import parse_scope
from radd.modules.comments import service
from radd.modules.comments.models import Comment
from radd.modules.comments.schemas import CommentAnchor, CommentCreate
from radd.modules.comments.types import CommentSlice
from radd.modules.items import service as items
from radd.modules.items.schemas import ItemCreate
from radd.modules.projects import service as projects
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.auth.types import LoginMethod


@pytest.fixture
async def world():
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        author = User(email=f"cp-{uuid.uuid4()}@example.com", name="Author", instance_role="admin")
        reader = User(email=f"cp-{uuid.uuid4()}@example.com", name="Reader", instance_role="admin")
        db.add_all([author, reader])
        await db.flush()
        project = await projects.create_project(db, ProjectCreate(key=f"CP{uuid.uuid4().hex[:5].upper()}", name="Pages"), actor_id=author.id)
        item = await items.create_item(db, ItemCreate(project_id=project.id, title="Long thread"), actor=author)
        yield db, author, reader, item
        await db.rollback()
    await engine.dispose()


async def test_visible_pages_skip_hidden_rows_without_offset_drift(world):
    db, author, reader, item = world
    reader.token_scope = parse_scope({"global": ["item.read"]})
    timestamp = datetime(2026, 1, 1)
    visible = []
    for i in range(125):
        row = Comment(entity_type="item", entity_id=item.id, author_id=author.id,
                      body=str(i), visibility="internal" if i % 3 == 0 else "public",
                      created_at=timestamp, updated_at=timestamp)
        db.add(row)
        await db.flush()
        if row.visibility == "public":
            visible.append(row)
    expected = [row.id for row in sorted(visible, key=lambda row: row.id, reverse=True)]
    first = await service.comment_page(db, item.id, reader, limit=20)
    assert len(first.comments) == 20 and first.older_cursor
    seen = [row.id for row in reversed(first.comments)]
    # The cursor remains valid after its row is removed and a newer comment arrives.
    await db.delete(await db.get(Comment, first.comments[0].id))
    db.add(Comment(entity_type="item", entity_id=item.id, author_id=author.id,
                   body="new", visibility="public", created_at=timestamp + timedelta(days=1)))
    await db.flush()
    cursor = first.older_cursor
    while cursor:
        page = await service.comment_page(db, item.id, reader, limit=20, before=cursor)
        assert len(page.comments) <= 20
        seen.extend(row.id for row in reversed(page.comments))
        cursor = page.older_cursor
    assert seen == expected
    assert len(seen) == len(set(seen))


async def test_parent_read_relationship_applies_to_legacy_and_paged_reads(world):
    db, author, reader, item = world
    await service.create_comment(db, item.id, CommentCreate(body="private issue discussion"), author)
    reader.token_scope = parse_scope({"global": ["item.read@own"]})
    for read in (service.list_comments, service.comment_page):
        with pytest.raises(NotFoundError):
            await read(db, item.id, reader)


async def test_inline_and_discussion_windows_do_not_hide_each_other(world):
    db, author, reader, item = world
    plain = await service.create_comment(db, item.id, CommentCreate(body="ordinary"), author)
    inline = await service.create_comment(db, item.id, CommentCreate(body="anchored", anchor=CommentAnchor(quote="Long")), author)
    assert [row.id for row in (await service.comment_page(db, item.id, reader, section=CommentSlice.DISCUSSION)).comments] == [plain.id]
    assert [row.id for row in (await service.comment_page(db, item.id, reader, section=CommentSlice.INLINE)).comments] == [inline.id]
    for cursor in ("not base64", "c2VjcmV0"):
        with pytest.raises(HTTPException) as error:
            await service.comment_page(db, item.id, reader, before=cursor)
        assert error.value.status_code == 422


@pytest.mark.parametrize("authority", ["reader", "internal", "manager"])
async def test_sql_visibility_matches_the_shared_audience_policy(world, authority):
    from radd.modules.comments.models import CommentVisibilityTeam
    from radd.modules.comments.visibility import internal_comment_visible
    from radd.modules.teams import service as teams
    from radd.modules.teams.schemas import TeamCreate

    db, author, reader, item = world
    mine = await teams.create_team(db, TeamCreate(name=f"mine-{uuid.uuid4()}"), author.id)
    other = await teams.create_team(db, TeamCreate(name=f"other-{uuid.uuid4()}"), author.id)
    await teams.add_team_member(db, mine.id, reader.id, actor_id=author.id)
    allowed = ["item.read"]
    if authority == "internal":
        allowed.append("comment.read_internal")
    if authority == "manager":
        allowed.append("project.manage")
    reader.token_scope = parse_scope({"global": allowed})
    expected = set()
    for own in (False, True):
        for visibility in ("public", "internal"):
            for audience in (set(), {mine.id}, {other.id}):
                row = Comment(entity_type="item", entity_id=item.id,
                              author_id=reader.id if own else author.id,
                              body="audience test", visibility=visibility)
                db.add(row)
                await db.flush()
                for team_id in audience:
                    db.add(CommentVisibilityTeam(comment_id=row.id, team_id=team_id))
                if visibility == "public" or internal_comment_visible(
                    is_author=own, has_read_internal=authority == "internal",
                    has_manage=authority == "manager", comment_teams=audience, actor_teams={mine.id},
                ):
                    expected.add(row.id)
    await db.flush()
    page = await service.comment_page(db, item.id, reader, limit=200)
    assert {comment.id for comment in page.comments} == expected


async def test_http_feed_is_bounded_and_rejects_invalid_pagination(world):
    import httpx
    from radd.app import create_app
    from radd.modules.auth import service as auth
    from radd.modules.auth.types import SESSION_COOKIE_NAME

    db, author, reader, item = world
    for i in range(51):
        db.add(Comment(entity_type="item", entity_id=item.id, author_id=author.id,
                       body=f"row {i}", visibility="public"))
    cookie = await auth.create_session(db, reader, method=LoginMethod.PASSWORD)
    await db.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://test",
                                 cookies={SESSION_COOKIE_NAME: cookie}) as client:
        path = f"/api/v1/items/{item.id}/comments/feed"
        response = await client.get(path)
        assert response.status_code == 200
        data = response.json()
        assert len(data["comments"]) == 50
        older = await client.get(path, params={"before": data["older_cursor"]})
        assert len(older.json()["comments"]) == 1
        assert older.json()["older_cursor"] is None
        for params in ({"limit": 201}, {"limit": 0}, {"before": "malformed"}, {"section": "unknown"}):
            assert (await client.get(path, params=params)).status_code == 422
        await client.post("/api/v1/auth/logout")


async def test_unknown_author_reads_updates_and_resolves_without_becoming_the_actor(world):
    from radd.modules.comments.schemas import CommentUpdate
    db, author, reader, item = world
    unknown = await service.create_comment(db, item.id, CommentCreate(body='unknown', author_id=None), author)
    assert unknown.author is None
    ordinary = await service.create_comment(db, item.id, CommentCreate(body='ordinary'), author)
    assert ordinary.author.id == author.id
    override = await service.create_comment(db, item.id, CommentCreate(body='other', author_id=reader.id), author)
    assert override.author.id == reader.id
    page = await service.comment_page(db, item.id, author)
    assert next(c for c in page.comments if c.id == unknown.id).author is None
    updated = await service.update_comment(db, unknown.id, CommentUpdate(body='edited'), author)
    assert updated.author is None
