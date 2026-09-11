"""Settings option windows preserve field authority, catalog order and migration semantics."""

import uuid
from datetime import timedelta

from sqlalchemy import event, select

from radd.clock import utcnow
from radd.modules.auth.models import GlobalRoleGrant, User
from radd.modules.fields.models import FieldDefinition, FieldProject
from test_field_scope_authority import scope_world as _scope_world

scope_world = _scope_world


async def test_option_windows_are_authorized_ordered_literal_and_lean(scope_world):
    db, client, projects, definitions, scoped_key, _ = scope_world
    values = [f"Option {i:03}" for i in range(126)]
    values[103] = "Literal %_ option"
    field = FieldDefinition(
        key="options_" + uuid.uuid4().hex[:12], name="Windowed options", type="select",
        options=values, default_value=values[-1], source="user",
        project_links=[FieldProject(project_id=projects[0].id)],
    )
    db.add(field)
    await db.flush()
    path = f"/api/v1/fields/definitions/{field.id}"
    statements = []

    def capture(conn, cursor, sql, parameters, context, executemany):
        statements.append(sql)

    event.listen(db.bind.sync_engine, "before_cursor_execute", capture)
    try:
        lean = await client.get(path, params={"include_options": "false"})
        assert lean.status_code == 200, lean.text
        assert lean.json()["options"] is None
        assert lean.json()["option_count"] == 126
        assert lean.json()["default_value"] == values[-1]
        # Count stays in SQL; no complete options column is returned by the projection.
        assert not any("field_definitions.options AS options" in s for s in statements)
        seen = []
        for offset, size in [(0, 50), (50, 50), (100, 26)]:
            response = await client.get(path + "/options", params={"offset": offset})
            assert response.status_code == 200, response.text
            assert len(response.json()) == size and response.headers["X-Total-Count"] == "126"
            seen.extend(response.json())
        assert seen == values
    finally:
        event.remove(db.bind.sync_engine, "before_cursor_execute", capture)
    assert (await client.get(path)).json()["options"] == values  # Complete compatibility read.
    response = await client.get(path + "/options", params={"q": "%_"})
    assert response.json() == [values[103]] and response.headers["X-Total-Count"] == "1"
    response = await client.get(path + "/options", params={"exclude": values[0], "offset": 100})
    assert response.json() == values[101:] and response.headers["X-Total-Count"] == "125"
    for invalid in [{"limit": 201}, {"offset": -1}, {"q": "x" * 201}]:
        assert (await client.get(path + "/options", params=invalid)).status_code == 422
    for hidden in [definitions[0].id, definitions[-1].id, uuid.uuid4()]:
        for suffix in ["?include_options=false", "/options"]:
            response = await client.get(f"/api/v1/fields/definitions/{hidden}{suffix}")
            assert response.status_code == 404
    # SQL/JSON null options (ordinary non-select definitions) are valid empty catalogs.
    response = await client.get(f"/api/v1/fields/definitions/{definitions[1].id}/options")
    assert response.json() == [] and response.headers["X-Total-Count"] == "0"
    client.cookies.clear()
    client.headers["Authorization"] = "Bearer " + scoped_key
    assert (await client.get(path + "/options")).status_code == 200
    assert (await client.get(f"/api/v1/fields/definitions/{definitions[0].id}/options")).status_code == 404


async def test_option_reads_follow_expired_authority(scope_world):
    db, client, _, definitions, _, _ = scope_world
    actor = await db.scalar(select(User).where(User.name == "Field editor"))
    for grant in await db.scalars(select(GlobalRoleGrant).where(GlobalRoleGrant.user_id == actor.id)):
        grant.expires_at = utcnow() - timedelta(seconds=1)
    await db.flush()
    db.info.clear()
    for suffix in ["?include_options=false", "/options?q=hidden"]:
        assert (await client.get(f"/api/v1/fields/definitions/{definitions[1].id}{suffix}")).status_code == 404


async def test_lean_option_mutations_preserve_off_page_defaults_and_required_migration(scope_world):
    db, client, projects, _, _, _ = scope_world
    values = [f"Value {i:03}" for i in range(126)]
    field = FieldDefinition(
        key="defaults_" + uuid.uuid4().hex[:12], name="Required options", type="select",
        options=values, required=True, default_value=values[-1], source="user",
        project_links=[FieldProject(project_id=projects[0].id)],
    )
    db.add(field)
    await db.flush()
    path = f"/api/v1/fields/{field.id}"
    response = await client.patch(path + "?include_options=false", json={"default_value": values[100]})
    assert response.status_code == 200 and response.json()["options"] is None
    response = await client.post(path + "/options?include_options=false", json={"values": ["Later addition"]})
    assert response.status_code == 200 and response.json()["options"] is None
    response = await client.get(f"/api/v1/fields/definitions/{field.id}/options", params={"offset": 100})
    assert response.json() == [*values[100:], "Later addition"]
    response = await client.post(path + "/options/remove?include_options=false", json={"value": values[100]})
    assert response.status_code == 422  # Required even when no issue carries the option.
    response = await client.post(path + "/options/remove?include_options=false", json={"value": values[100], "replace_with": values[-1]})
    assert response.status_code == 200, response.text
    assert response.json()["options"] is None and response.json()["default_value"] == values[-1]
    complete = (await client.get(f"/api/v1/fields/definitions/{field.id}")).json()
    assert complete["options"] == [v for v in [*values, "Later addition"] if v != values[100]]
    assert complete["option_count"] == 126
