"""Builtin-field access rules core (spec 36 → spec 92).

Builtin item fields (state/assignee/…) now use the SAME generic access framework
as custom fields — rules are grants on resource_type="builtin_field". These pin
the pure decision helpers (`builtin_write_denied`/`builtin_read_denied`):
default-open, restrict-on-grant, write⇒read, manage-bypasses, and per-project
SCOPE (a builtin grant scoped to project A only restricts on A).
"""

import uuid

from radd.modules.access.resolution import SubjectContext
from radd.modules.access.types import Access, GrantSubject
from radd.modules.fields.service import builtin_read_denied, builtin_write_denied
from radd.modules.fields.types import READ_RESTRICTABLE_BUILTINS, BuiltinItemField

LEAD_ROLE = uuid.uuid4()
ARTIST_TEAM = uuid.uuid4()
PROJECT_A = uuid.uuid4()
PROJECT_B = uuid.uuid4()


class Grant:
    def __init__(self, subject_type, subject_id, access, project_id=None):
        self.subject_type = subject_type.value
        self.subject_id = subject_id
        self.access = access.value
        self.project_id = project_id


WRITE_GRANTS = {
    "priority": [Grant(GrantSubject.ROLE, LEAD_ROLE, Access.WRITE)],
    "target_date": [
        Grant(GrantSubject.ROLE, LEAD_ROLE, Access.WRITE),
        Grant(GrantSubject.TEAM, ARTIST_TEAM, Access.WRITE),
    ],
}


def ctx(*, roles=(), teams=(), groups=(), manage=False):
    return SubjectContext(
        role_ids=frozenset(roles),
        team_ids=frozenset(teams),
        group_ids=frozenset(groups),
        has_manage=manage,
    )


def test_unruled_fields_stay_open():
    assert builtin_write_denied(["title", "description"], WRITE_GRANTS, ctx(), None) == []


def test_rule_denies_non_subjects_sorted():
    assert builtin_write_denied(["priority", "target_date", "title"], WRITE_GRANTS, ctx(), None) == [
        "priority",
        "target_date",
    ]


def test_matching_role_or_team_passes():
    assert builtin_write_denied(["priority", "target_date"], WRITE_GRANTS, ctx(roles=[LEAD_ROLE]), None) == []
    # The team grant covers target_date but not priority.
    assert builtin_write_denied(
        ["priority", "target_date"], WRITE_GRANTS, ctx(teams=[ARTIST_TEAM]), None
    ) == ["priority"]


def test_manage_flag_is_the_instance_admin_short_circuit():
    # RADD-816 (F5.2): the flag means INSTANCE ADMIN now — construction sites
    # stopped passing project.manage, so a pm-holder arrives as ctx() and is
    # denied unless the grant names them.
    assert builtin_write_denied(["priority"], WRITE_GRANTS, ctx(manage=True), None) == []
    assert builtin_write_denied(["priority"], WRITE_GRANTS, ctx(), None) == ["priority"]


def test_scoped_builtin_grant_only_restricts_its_project():
    grants = {"priority": [Grant(GrantSubject.ROLE, LEAD_ROLE, Access.WRITE, project_id=PROJECT_A)]}
    # On A: restricted — only the lead role writes.
    assert builtin_write_denied(["priority"], grants, ctx(), PROJECT_A) == ["priority"]
    assert builtin_write_denied(["priority"], grants, ctx(roles=[LEAD_ROLE]), PROJECT_A) == []
    # On B: the grant is out of scope → open to everyone.
    assert builtin_write_denied(["priority"], grants, ctx(), PROJECT_B) == []


# --- read rules (spec 50): blanked out of representations, not rejected on write ---

READ_GRANTS = {
    "assignee": [Grant(GrantSubject.ROLE, LEAD_ROLE, Access.READ)],
    "start_date": [Grant(GrantSubject.TEAM, ARTIST_TEAM, Access.READ)],
}


def test_read_denies_restricted_fields_for_non_subjects():
    assert builtin_read_denied(READ_GRANTS, ctx(), None) == ["assignee", "start_date"]


def test_read_matching_subject_or_manage_passes():
    assert builtin_read_denied(READ_GRANTS, ctx(roles=[LEAD_ROLE]), None) == ["start_date"]
    assert builtin_read_denied(READ_GRANTS, ctx(teams=[ARTIST_TEAM]), None) == ["assignee"]


def test_structural_identifiers_are_not_read_restrictable():
    for field in (BuiltinItemField.TITLE, BuiltinItemField.STATE, BuiltinItemField.PRIORITY):
        assert field not in READ_RESTRICTABLE_BUILTINS
    assert BuiltinItemField.ASSIGNEE in READ_RESTRICTABLE_BUILTINS
