"""Uninstall sweeps a plugin's atoms (RADD-818).

Roles hold atom STRINGS; removing a plugin used to leave roles, token scopes
and access grants referencing vocabulary the catalog no longer knew. The sweep
is the RADD-701 migration pattern at runtime: strip only what the plugin
DECLARED (never a shared umbrella), relation-qualified forms strip by base,
grants of its access-resource types are deleted, and the emitted event names
everything removed.

Rolled-back transactions on the compose DB.
"""

import json
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.kernel import RaddPlugin
from radd.kernel.specs import CrudResourceSpec, PermissionSpec
from radd.modules.access.models import AccessGrant
from radd.modules.auth import roles as auth_roles
from radd.modules.auth.schemas import RoleCreate
from radd.modules.pluginmgr.service import sweep_plugin_atoms


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


class _FakeResource:
    resource_type = "acmenote"


_PLUGIN = RaddPlugin(
    name="acme",
    description="sweep fixture",
    permissions=(PermissionSpec(key="acmenote.publish", scope="global"),),
    crud_resources=(CrudResourceSpec(key="acmenote", scope="global", label="acme notes", manage="global.manage"),),
    access_resources=(_FakeResource(),),
)


async def test_sweep_strips_declared_atoms_and_grants_only(db):
    # Historical JSON-null scopes are returned as Python None, despite matching
    # SQL IS NOT NULL. Uninstall must tolerate these unscoped credentials.
    from radd.modules.auth.models import ApiToken, User
    user = User(email=f"null-scope-{uuid.uuid4()}@example.com", name="Legacy token")
    db.add(user)
    await db.flush()
    token = ApiToken(user_id=user.id, name="legacy", token_hash=uuid.uuid4().hex, prefix_display="legacy")
    db.add(token)
    await db.flush()
    await db.execute(text("UPDATE api_tokens SET scopes = 'null'::jsonb WHERE id = :id"), {"id": token.id})
    # A role holding the plugin's atoms (one relation-qualified) AND a builtin.
    role = await auth_roles.create_role(
        db, RoleCreate(key=f"sw{uuid.uuid4().hex[:6]}", name="S", permissions=["item.read"])
    )
    await db.execute(
        text("UPDATE roles SET permissions = :p WHERE id = :id"),
        {
            "p": json.dumps(
                ["item.read", "acmenote.publish", "acmenote.create", "acmenote.publish@own"]
            ),
            "id": role.id,
        },
    )
    grant = AccessGrant(
        resource_type="acmenote",
        resource_id=str(uuid.uuid4()),
        subject_type="user",
        subject_id=uuid.uuid4(),
        access="read",
    )
    db.add(grant)
    await db.flush()

    summary = await sweep_plugin_atoms(db, _PLUGIN, actor_id=None)

    stored = (
        await db.execute(text("SELECT permissions FROM roles WHERE id = :id"), {"id": role.id})
    ).scalar()
    atoms = stored if isinstance(stored, list) else json.loads(stored)
    # The plugin's atoms are gone — the unqualified, the CRUD, and the
    # relation-qualified form (stripped by BASE); the builtin survives.
    assert atoms == ["item.read"]
    assert (await db.get(AccessGrant, grant.id)) is None
    assert "acmenote.publish" in summary["stripped_atoms"]
    assert summary["dropped_grants"] == 1
    assert role.key in summary["swept_roles"]
    # global.manage is a SHARED umbrella the plugin merely referenced — it is
    # never in the strip set.
    assert "global.manage" not in summary["stripped_atoms"]
