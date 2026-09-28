"""RADD-1428: the custom-field OpenAPI projection follows every mutation, and
every reader gets the same one.

`extend_options` (the importer's additive path, RADD-949) never refreshed the
process-wide schema cache, so a select option added by an import was missing
from `/openapi.json` and the MCP schemas until an unrelated field write. And the
MCP catalog refreshed that cache itself — without the restricted keys — so one
`tools/list` stripped every `x-restricted` hint for every OpenAPI reader until
the next field mutation. Rolled-back transactions on the compose DB; the cache
is restored to what it held before each test.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.access import service as access_service
from radd.modules.access.types import Access, GrantSubject
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.fields import openapi, service as fields_service
from radd.modules.fields.schemas import FieldDefinitionCreate
from radd.modules.fields.types import FieldType
from radd.modules.mcp.catalog import live_projections


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
def cache_restored():
    """The cache is process-wide; leave it as found."""
    before = dict(openapi.schema_cache.properties)
    yield
    openapi.schema_cache.properties = before


async def _select(db, *options: str):
    return await fields_service.create_field(
        db,
        FieldDefinitionCreate(
            key=f"sc_{uuid.uuid4().hex[:8]}", name="Bucket", type=FieldType.SELECT,
            options=list(options),
        ),
    )


async def test_extend_options_refreshes_the_projection(db, cache_restored):
    field = await _select(db, "a", "b")
    assert openapi.schema_cache.properties[field.key]["enum"] == ["a", "b"]

    assert await fields_service.extend_options(db, field.id, ["c"]) == ["c"]

    assert openapi.schema_cache.properties[field.key]["enum"] == ["a", "b", "c"]


async def test_the_mcp_projection_carries_restricted_hints_and_leaves_the_cache_alone(
    db, cache_restored
):
    field = await _select(db, "x")
    someone = User(
        email=f"sc-{uuid.uuid4().hex[:8]}@example.com", name="Grantee",
        instance_role=InstanceRole.MEMBER.value,
    )
    db.add(someone)
    await db.flush()
    await access_service.add_grant(
        db, fields_service.FIELD_RESOURCE, str(field.id),
        subject_type=GrantSubject.USER, subject_id=someone.id, access=Access.READ.value,
    )
    sentinel = {"sentinel": {"type": "string"}}
    openapi.schema_cache.properties = dict(sentinel)

    properties, _link_types = await live_projections(db)

    # The live projection knows the grant…
    assert properties[field.key]["x-restricted"] is True
    assert properties[field.key]["enum"] == ["x"]
    # …and reading it wrote nothing: the cache is exactly what it was.
    assert openapi.schema_cache.properties == sentinel


async def test_the_pure_projection_and_the_cache_agree(db, cache_restored):
    """`properties_for` is the one builder; `refresh` writes what it returns."""
    definitions, restricted = await fields_service._live_projection(db)
    openapi.refresh(definitions, restricted)
    assert openapi.schema_cache.properties == openapi.properties_for(definitions, restricted)
    assert openapi.schema_cache.properties == await fields_service.schema_properties(db)
