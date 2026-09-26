"""Form defaults cover what a project actually offers (RADD-801). The first test
walks `ItemCreate` and fails when a field is neither carried by a default nor
named in the exclusion list, so a new item attribute cannot silently miss forms.
The rest assert the values actually LAND: a field stored and then dropped at
submit is the same bug.
"""

import uuid
from datetime import date


from radd.modules.forms import service as forms_service
from radd.modules.forms.schemas import (
    DEFAULTS_COVERAGE,
    FormCreate,
    FormDefaults,
    FormSubmit,
    FormUpdate,
)
from radd.modules.items.schemas import ItemCreate
from radd.modules.itemtypes import service as itemtypes_service
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate


def test_every_item_field_is_carried_or_excluded_with_a_reason():
    """THE drift guard. If this fails you added a field to `ItemCreate`: in
    `DEFAULTS_COVERAGE`, name the `FormDefaults` key that carries it, or say in
    one line why a form author should not set it."""
    missing = sorted(set(ItemCreate.model_fields) - set(DEFAULTS_COVERAGE))
    assert not missing, (
        "ItemCreate fields with no entry in DEFAULTS_COVERAGE: "
        + ", ".join(missing)
        + " — add a FormDefaults key, or an exclusion with its reason."
    )


def test_the_coverage_map_describes_reality():
    """The map is only worth having if it cannot lie: every key it claims must
    exist on `FormDefaults`, every exclusion must carry a reason, and it must not
    name `ItemCreate` fields that are gone."""
    stale = sorted(set(DEFAULTS_COVERAGE) - set(ItemCreate.model_fields))
    assert not stale, f"DEFAULTS_COVERAGE names fields ItemCreate no longer has: {stale}"

    for item_field, (defaults_key, reason) in DEFAULTS_COVERAGE.items():
        if defaults_key is None:
            assert reason, f"{item_field} is excluded with no reason given"
        else:
            assert defaults_key in FormDefaults.model_fields, (
                f"{item_field} claims to be carried by FormDefaults.{defaults_key}, "
                "which does not exist"
            )


def test_kind_and_type_are_different_axes():
    """The trap that made the gap confusing: `kind` is the epic/issue/subtask
    ladder and reads as "type" in the UI, while spec 51's TYPE is Bug/Feature.
    Both have to be settable, or the obvious control sets the wrong thing."""
    assert DEFAULTS_COVERAGE["kind"][0] == "kind"
    assert DEFAULTS_COVERAGE["type_id"][0] == "type_name"


# --- and the values actually land ---------------------------------------------


async def test_a_form_default_issue_type_lands_on_the_item(db, admin):
    """The reported gap, end to end."""
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"FD{uuid.uuid4().hex[:4].upper()}", name="Defaults")
    )
    # A project seeds its default types (spec 51), so use one rather than
    # creating a duplicate — which is what the form author would pick from too.
    bug = next(
        t for t in await itemtypes_service.list_types(db, project.id) if t.name == "Bug"
    )
    form = await forms_service.create_form(
        db,
        FormCreate(
            project_id=project.id,
            name="Report a bug",
            defaults=FormDefaults(type_name="Bug"),
        ),
        actor=admin,
    )

    item = await forms_service.submit_form(
        db, form.id, FormSubmit(title="It broke"), admin
    )
    assert item.type is not None and item.type.id == bug.id


async def test_an_unknown_type_falls_back_rather_than_refusing(db, admin):
    """A renamed type must not stop people filing requests — the project's
    default takes over, exactly as it would for a hand-created item."""
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"FD{uuid.uuid4().hex[:4].upper()}", name="Defaults")
    )
    form = await forms_service.create_form(
        db,
        FormCreate(
            project_id=project.id,
            name="Report",
            defaults=FormDefaults(type_name="A type that was renamed"),
        ),
        actor=admin,
    )
    item = await forms_service.submit_form(db, form.id, FormSubmit(title="Still works"), admin)
    assert item.id is not None


async def test_the_other_recovered_defaults_land(db, admin):
    """Points, the flag and the dates — added by specs 70/24 and never wired to
    forms until now."""
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"FD{uuid.uuid4().hex[:4].upper()}", name="Defaults")
    )
    form = await forms_service.create_form(
        db,
        FormCreate(
            project_id=project.id,
            name="Planned work",
            defaults=FormDefaults(
                flagged=True,
                estimate_points=3,
                start_date=date(2026, 8, 1),
                target_date=date(2026, 8, 31),
            ),
        ),
        actor=admin,
    )
    item = await forms_service.submit_form(db, form.id, FormSubmit(title="Scheduled"), admin)
    assert item.flagged is True
    assert item.estimate_points == 3
    assert item.start_date == date(2026, 8, 1)
    assert item.target_date == date(2026, 8, 31)


async def test_defaults_survive_an_edit(db, admin):
    """`update_form` copies field by field, and that is exactly how
    `team_picker_enabled` was added and silently ignored during RADD-798. A
    default that cannot be edited is as good as absent."""
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"FD{uuid.uuid4().hex[:4].upper()}", name="Defaults")
    )
    form = await forms_service.create_form(
        db, FormCreate(project_id=project.id, name="Ask"), actor=admin
    )
    updated = await forms_service.update_form(
        db,
        form.id,
        FormUpdate(defaults=FormDefaults(type_name="Task", flagged=True)),
        actor=admin,
    )
    assert updated.defaults.type_name == "Task"
    assert updated.defaults.flagged is True
