"""RADD-883: server-side q/limit/offset + X-Total-Count on the big collections.

The settings pages filter client-side (RADD-882); these params exist for the
payload problem — a 2,293-row /teams response at 10× scale — and for pickers
that flip to server search. Pins: contains-match with WILDCARD ESCAPING (a
search for "100%" must not match everything), slicing, and the pre-pagination
count in the header only when `limit` was passed.

DB-backed, flushed, never committed — the session rolls back at teardown.
"""

import uuid

import pytest
from fastapi import Response
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.apitypes import TOTAL_COUNT_HEADER
from radd.config import settings as config
from radd.modules.auth import service as auth_service
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.labels import service as labels_service
from radd.modules.labels.router import list_labels as labels_endpoint
from radd.modules.labels.schemas import LabelCreate
from radd.modules.teams import service as teams_service
from radd.modules.teams.schemas import TeamCreate


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def admin(db) -> User:
    user = User(
        email=f"listsearch-{uuid.uuid4().hex[:8]}@example.com",
        name="List Search Admin",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


def _tag() -> str:
    return uuid.uuid4().hex[:6]


async def test_labels_q_matches_contains_case_insensitive(db):
    tag = _tag()
    for name in (f"Render {tag}", f"render-farm {tag}", f"Pipeline {tag}"):
        await labels_service.create_label(db, LabelCreate(name=name))
    hits = await labels_service.list_labels(db, q=f"rend")
    names = {label.name for label in hits}
    assert f"Render {tag}" in names and f"render-farm {tag}" in names
    assert f"Pipeline {tag}" not in names


async def test_q_wildcards_are_literal(db):
    tag = _tag()
    await labels_service.create_label(db, LabelCreate(name=f"100% done {tag}"))
    await labels_service.create_label(db, LabelCreate(name=f"fully done {tag}"))
    # A literal % matches only the row that contains one — not everything.
    hits = await labels_service.list_labels(db, q="0% ")
    assert {label.name for label in hits} == {f"100% done {tag}"}
    # A literal underscore likewise must not act as single-char wildcard.
    await labels_service.create_label(db, LabelCreate(name=f"snake_case {tag}"))
    await labels_service.create_label(db, LabelCreate(name=f"snakeXcase {tag}"))
    hits = await labels_service.list_labels(db, q="snake_")
    assert {label.name for label in hits} == {f"snake_case {tag}"}


async def test_teams_limit_offset_slice_and_count(db):
    tag = _tag()
    for i in range(5):
        await teams_service.create_team(db, TeamCreate(name=f"Slice {tag} {i}"))
    page1 = await teams_service.list_teams(db, q=f"Slice {tag}", limit=2, offset=0)
    page2 = await teams_service.list_teams(db, q=f"Slice {tag}", limit=2, offset=2)
    assert [t.name for t in page1] == [f"Slice {tag} 0", f"Slice {tag} 1"]
    assert [t.name for t in page2] == [f"Slice {tag} 2", f"Slice {tag} 3"]
    assert await teams_service.count_teams(db, q=f"Slice {tag}") == 5


async def test_labels_endpoint_sets_total_header_only_when_paged(db, admin):
    tag = _tag()
    for i in range(3):
        await labels_service.create_label(db, LabelCreate(name=f"Hdr {tag} {i}"))
    paged = Response()
    rows = await labels_endpoint(
        paged, db, admin, q=f"Hdr {tag}", limit=2, offset=0
    )
    assert len(rows) == 2
    assert paged.headers[TOTAL_COUNT_HEADER] == "3"
    unpaged = Response()
    rows = await labels_endpoint(unpaged, db, admin, q=f"Hdr {tag}", limit=None, offset=0)
    assert len(rows) == 3
    assert TOTAL_COUNT_HEADER not in unpaged.headers


async def test_audit_q_matches_type_and_payload(db):
    """RADD-884: the audit trail's q matches the event type or payload text."""
    from radd.modules.events.models import Event
    from radd.modules.events.service import query_events

    tag = _tag()
    db.add(Event(event_type=f"probe.created", entity_type="probe", entity_id=tag,
                 payload={"title": f"needle-{tag}"}))
    db.add(Event(event_type=f"probe.created", entity_type="probe", entity_id=tag,
                 payload={"title": "unrelated"}))
    await db.flush()
    hits = await query_events(db, q=f"needle-{tag}")
    assert len(hits) == 1
    assert hits[0].payload["title"] == f"needle-{tag}"


async def test_directory_pagination_and_count(db):
    tag = _tag()
    for i in range(4):
        db.add(
            User(
                email=f"dir-{tag}-{i}@example.com",
                name=f"Directory {tag} {i}",
                instance_role=InstanceRole.MEMBER.value,
            )
        )
    await db.flush()
    rows = await auth_service.list_users(db, q=f"Directory {tag}", limit=3, offset=0)
    assert len(rows) == 3
    assert await auth_service.count_users(db, q=f"Directory {tag}") == 4
