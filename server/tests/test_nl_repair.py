"""NL→SLQ value repair (spec 103 addendum): generated queries get REAL values.

The property under test: SLQ stays exact (nothing here touches the compiler);
the NL layer resolves 'jimmy' to the actual account, 'in progress' to the
exact state name, a guessed option to the curated one — and reports every
substitution. Sentinels, dates, item keys, `~` substrings, and verbatim-real
values pass through untouched.

DB-backed; flushed, never committed.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.modules.ai import nlrepair
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.fields import service as fields_service
from radd.modules.fields.schemas import FieldDefinitionCreate
from radd.modules.fields.types import FieldType
from radd.modules.items import slq
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def world(db):
    """A user with a real name, a project (with default states), and a select field."""
    jimmy = User(
        email=f"jimmy-{uuid.uuid4().hex[:6]}@example.com",
        name="Jimmy Lee Barlow",
        instance_role=InstanceRole.MEMBER.value,
    )
    db.add(jimmy)
    await db.flush()
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"NR{uuid.uuid4().hex[:4].upper()}", name="Repair P")
    )
    severity = await fields_service.create_field(
        db,
        FieldDefinitionCreate(
            key=f"severity_{uuid.uuid4().hex[:4]}",
            name="Severity",
            type=FieldType.SELECT,
            options=["sev1 minor", "sev2 major", "sev3 critical"],
        ),
    )
    definitions = {severity.key: severity}
    return jimmy, project, severity, definitions


async def _repair(db, definitions, text):
    query, repairs = await nlrepair.repair_query(
        db, slq.parse(text), definitions_by_key=definitions
    )
    return slq.render(query), repairs


async def test_first_name_resolves_to_the_real_account(db, world):
    jimmy, _, _, definitions = world
    rendered, repairs = await _repair(db, definitions, "assignee = jimmy")
    assert jimmy.email in rendered  # the query now names the actual account
    assert len(repairs) == 1
    assert repairs[0].original == "jimmy"
    assert repairs[0].label == "Jimmy Lee Barlow"
    assert "Jimmy Lee Barlow" in repairs[0].note()


async def test_state_case_and_paraphrase_repair(db, world):
    _, _, _, definitions = world
    # Default workflow states include "In Progress" — SLQ state match is
    # case-sensitive, so the lowercase guess would silently match nothing.
    rendered, repairs = await _repair(db, definitions, 'state = "in progress"')
    assert "'In Progress'" in rendered
    assert repairs and repairs[0].replacement == "In Progress"


async def test_state_word_with_no_real_state_becomes_its_category(db, world):
    """RADD-1140: "fixed" is no typo of Triage/Backlog/Todo/In Progress/Code
    Review/Done/Canceled — it is a CATEGORY spoken as a state. The comparison
    is rewritten rather than left to compile into a silent zero-row query, and
    reported on the same path a people-repair is."""
    _, _, _, definitions = world
    rendered, repairs = await _repair(db, definitions, "state = Fixed")
    assert rendered == "category = done"
    assert [(r.kind, r.field, r.original, r.replacement) for r in repairs] == [
        (nlrepair.RepairKind.CATEGORY, "state", "Fixed", "category = done")
    ]
    assert "read 'Fixed' as category = done" in repairs[0].note()

    # The not-done words flip the operator; the ancestor and delegated forms
    # rewrite the same way, keeping their prefix.
    rendered, _ = await _repair(db, definitions, "state = open")
    assert rendered == "category != done"
    rendered, _ = await _repair(db, definitions, "state != open")
    assert rendered == "category = done"
    rendered, _ = await _repair(db, definitions, "epic.state = closed AND priority = high")
    assert rendered == "epic.category = done AND priority = high"
    rendered, repairs = await _repair_worklog(db, definitions, "issue.state = resolved")
    assert rendered == "issue.category = done"
    assert repairs[0].field == "issue.state"


async def test_state_that_exists_nowhere_is_kept_and_reported(db, world):
    _, _, _, definitions = world
    rendered, repairs = await _repair(db, definitions, "state = Nonexistentia")
    assert rendered == "state = Nonexistentia"
    assert [r.kind for r in repairs] == [nlrepair.RepairKind.UNKNOWN_STATE]
    assert repairs[0].replacement == ""
    assert "no state named 'Nonexistentia'" in repairs[0].note()
    # Membership: each unknown name is reported, a real one passes untouched.
    rendered, repairs = await _repair(db, definitions, "state IN (Done, Nonexistentia)")
    assert rendered == "state IN (Done, Nonexistentia)"
    assert [(r.kind, r.original) for r in repairs] == [
        (nlrepair.RepairKind.UNKNOWN_STATE, "Nonexistentia")
    ]
    # Other entity fields keep the old silence (`assignee = zzqqxx` above).


async def test_custom_select_option_repairs_to_the_curated_value(db, world):
    _, _, severity, definitions = world
    rendered, repairs = await _repair(db, definitions, f"{severity.key} = critical")
    assert "'sev3 critical'" in rendered
    assert repairs and repairs[0].field == severity.key


async def test_sentinels_dates_and_keys_are_never_touched(db, world):
    _, _, _, definitions = world
    text = "assignee = me AND reporter = none AND created > today-2w AND key = TD-12"
    rendered, repairs = await _repair(db, definitions, text)
    assert repairs == []
    assert "me" in rendered and "none" in rendered and "today-2w" in rendered


async def test_contains_keeps_its_substring(db, world):
    _, _, _, definitions = world
    rendered, repairs = await _repair(db, definitions, 'title ~ "jimmy"')
    assert repairs == []
    assert "'jimmy'" in rendered


async def test_verbatim_real_values_pass_untouched(db, world):
    jimmy, _, _, definitions = world
    rendered, repairs = await _repair(db, definitions, f"assignee = {jimmy.email}")
    assert repairs == []


async def test_garbage_left_alone_for_the_honest_empty_result(db, world):
    _, _, _, definitions = world
    rendered, repairs = await _repair(db, definitions, "assignee = zzqqxx")
    assert repairs == []
    assert "zzqqxx" in rendered


async def test_membership_and_plugin_user_fields_repair_each_value(db, world):
    jimmy, _, _, definitions = world
    rendered, repairs = await _repair(db, definitions, "logged_by = barlow")
    assert jimmy.email in rendered  # spec-97 plugin field borrows the people candidates
    assert repairs and repairs[0].field == "logged_by"


# --- the worklog dialect (spec 98: bare worklog fields + issue.* delegation) ---


async def _repair_worklog(db, definitions, text):
    query, repairs = await nlrepair.repair_query(
        db, slq.parse(text), definitions_by_key=definitions, dialect="worklog"
    )
    return slq.render(query), repairs


async def test_worklog_author_and_delegated_issue_fields_repair(db, world):
    jimmy, _, _, definitions = world
    rendered, repairs = await _repair_worklog(
        db, definitions, 'author = jimmy AND issue.state = "in progress"'
    )
    assert jimmy.email in rendered
    assert "'In Progress'" in rendered
    fields = {repair.field for repair in repairs}
    assert fields == {"author", "issue.state"}


async def test_worklog_category_repairs_to_the_curated_name(db, world):
    from radd.modules.timelogging.models import WorkCategory

    _, _, _, definitions = world
    db.add(WorkCategory(name=f"Code Review {uuid.uuid4().hex[:4]}"))
    await db.flush()
    rendered, repairs = await _repair_worklog(db, definitions, "category = review")
    assert repairs and repairs[0].field == "category"
    assert "Code Review" in rendered


async def test_worklog_own_scalars_stay_untouched(db, world):
    _, _, _, definitions = world
    rendered, repairs = await _repair_worklog(
        db, definitions, "worked_on >= today-1w AND time > 2h AND issue = TD-12"
    )
    assert repairs == []
