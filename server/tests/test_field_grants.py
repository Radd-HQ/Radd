"""Field access grants (spec 07 → spec 92) — the pure resolution core.

Field read/write grants now live in the generic access framework: definitions are
duck-typed with an id + key, grants are AccessGrant-shaped rows keyed by field id
in the FieldAccessContext (with the actor's per-project subjects + the project).
Same semantics as before (open until restricted, write implies read, manage
bypasses) plus per-project SCOPE and a USER subject. Comment-visibility gating
rides along.
"""

import uuid

import pytest

from radd.exceptions import ForbiddenError
from radd.modules.auth.authz import Permission
from radd.modules.comments.service import _check_internal
from radd.modules.comments.types import CommentVisibility
from radd.modules.fields.service import (
    FieldAccessContext,
    field_readable,
    field_writable,
    readable,
    readable_keys,
    writable_check,
)
from radd.modules.access.types import Access, GrantSubject

LEADS_TEAM = uuid.uuid4()
TRIAGER_ROLE = uuid.uuid4()
OTHER_ROLE = uuid.uuid4()
A_USER = uuid.uuid4()
PROJECT_A = uuid.uuid4()
PROJECT_B = uuid.uuid4()


class StubGrant:
    """AccessGrant-shaped: subject + access + optional project scope."""

    def __init__(self, subject_type, subject_id, access, project_id=None):
        self.subject_type = subject_type.value
        self.subject_id = subject_id
        self.access = access.value
        self.project_id = project_id


class StubDef:
    """Duck-types FieldDefinition (id + key)."""

    def __init__(self, key, *grants):
        self.id = uuid.uuid4()
        self.key = key
        self.grants = list(grants)


def role_grant(role_id, access, project_id=None):
    return StubGrant(GrantSubject.ROLE, role_id, access, project_id)


def team_grant(team_id, access, project_id=None):
    return StubGrant(GrantSubject.TEAM, team_id, access, project_id)


def user_grant(user_id, access, project_id=None):
    return StubGrant(GrantSubject.USER, user_id, access, project_id)


def ctx(defs=(), *, roles=(), teams=(), user=None, manage=False, project_id=None):
    return FieldAccessContext(
        role_ids=frozenset(roles),
        team_ids=frozenset(teams),
        has_manage=manage,
        user_id=user,
        project_id=project_id,
        grants_by_field={str(d.id): d.grants for d in defs},
    )


# --- default-open semantics: no rows for an access -> that access is open ---


def test_no_grants_means_open_read_and_write():
    d = StubDef("severity")
    assert field_readable(d, ctx([d]))
    assert field_writable(d, ctx([d]))


def test_write_grants_alone_leave_read_open():
    d = StubDef("estimate", role_grant(TRIAGER_ROLE, Access.WRITE))
    assert field_readable(d, ctx([d]))  # no read rows -> anyone with item.read
    assert not field_writable(d, ctx([d]))


def test_read_grants_alone_leave_write_open():
    d = StubDef("budget", team_grant(LEADS_TEAM, Access.READ))
    assert not field_readable(d, ctx([d]))
    assert field_writable(d, ctx([d]))


# --- read grants ---


def test_read_requires_a_matching_subject():
    d = StubDef("budget", team_grant(LEADS_TEAM, Access.READ))
    assert field_readable(d, ctx([d], teams=[LEADS_TEAM]))
    assert not field_readable(d, ctx([d], teams=[uuid.uuid4()]))
    assert not field_readable(d, ctx([d], roles=[TRIAGER_ROLE]))


def test_role_read_grant_matches_role_subjects_only():
    d = StubDef("budget", role_grant(TRIAGER_ROLE, Access.READ))
    assert field_readable(d, ctx([d], roles=[TRIAGER_ROLE]))
    # A team id equal to the granted role id must NOT match (subject_type is checked).
    assert not field_readable(d, ctx([d], teams=[TRIAGER_ROLE]))


def test_user_subject_grant():
    d = StubDef("budget", user_grant(A_USER, Access.READ))
    assert field_readable(d, ctx([d], user=A_USER))
    assert not field_readable(d, ctx([d], user=uuid.uuid4()))


def test_write_grant_confers_read():
    d = StubDef(
        "budget",
        team_grant(LEADS_TEAM, Access.READ),
        role_grant(TRIAGER_ROLE, Access.WRITE),
    )
    assert field_readable(d, ctx([d], roles=[TRIAGER_ROLE]))  # writer may see it
    assert not field_readable(d, ctx([d], roles=[OTHER_ROLE]))


def test_manage_flag_means_instance_admin_and_short_circuits():
    """RADD-816 (F5.2): the flag no longer means project.manage — construction
    sites pass the INSTANCE-ADMIN fact, and the fields layer (not the
    framework) short-circuits for the operator who administers the grants. A
    project manager without a naming grant is denied (the plain ctx below)."""
    d = StubDef("budget", team_grant(LEADS_TEAM, Access.READ))
    assert field_readable(d, ctx([d], manage=True))  # instance admin
    assert not field_readable(d, ctx([d]))  # a pm-holder constructs THIS now


# --- per-project SCOPE (spec 92) ---


def test_scoped_grant_applies_only_in_its_project():
    # A read grant scoped to project A restricts read ON A only.
    d = StubDef("budget", team_grant(LEADS_TEAM, Access.READ, project_id=PROJECT_A))
    # On A: restricted — the team can read, others can't.
    assert field_readable(d, ctx([d], teams=[LEADS_TEAM], project_id=PROJECT_A))
    assert not field_readable(d, ctx([d], teams=[uuid.uuid4()], project_id=PROJECT_A))
    # On B: the grant is out of scope, so read is OPEN to everyone.
    assert field_readable(d, ctx([d], teams=[uuid.uuid4()], project_id=PROJECT_B))


def test_global_grant_applies_everywhere():
    d = StubDef("budget", team_grant(LEADS_TEAM, Access.READ))  # project_id None = global
    assert field_readable(d, ctx([d], teams=[LEADS_TEAM], project_id=PROJECT_A))
    assert not field_readable(d, ctx([d], teams=[uuid.uuid4()], project_id=PROJECT_B))


# --- write grants ---


def test_write_requires_a_write_grant_not_a_read_grant():
    d = StubDef(
        "budget",
        team_grant(LEADS_TEAM, Access.READ),
        team_grant(LEADS_TEAM, Access.WRITE),
        role_grant(TRIAGER_ROLE, Access.READ),
    )
    assert field_writable(d, ctx([d], teams=[LEADS_TEAM]))
    assert field_readable(d, ctx([d], roles=[TRIAGER_ROLE]))
    assert not field_writable(d, ctx([d], roles=[TRIAGER_ROLE]))


def test_admin_write_short_circuit():
    d = StubDef("budget", role_grant(TRIAGER_ROLE, Access.WRITE))
    assert field_writable(d, ctx([d], manage=True))  # instance admin


# --- list helpers the items module consumes ---


def test_readable_and_keys_filter_definitions():
    open_def = StubDef("severity")
    gated = StubDef("budget", team_grant(LEADS_TEAM, Access.READ))
    defs = [open_def, gated]
    assert readable(defs, ctx(defs)) == [open_def]
    assert readable_keys(defs, ctx(defs)) == {"severity"}
    assert readable_keys(defs, ctx(defs, teams=[LEADS_TEAM])) == {"severity", "budget"}
    assert readable_keys(defs, ctx(defs, manage=True)) == {"severity", "budget"}  # admin


def test_writable_check_raises_forbidden_listing_denied_keys():
    defs = [
        StubDef("severity"),
        StubDef("budget", role_grant(TRIAGER_ROLE, Access.WRITE)),
        StubDef("quota", role_grant(TRIAGER_ROLE, Access.WRITE)),
    ]
    writable_check(defs, {"severity": "high"}, ctx(defs))
    writable_check(defs, {"budget": 5, "quota": 1}, ctx(defs, roles=[TRIAGER_ROLE]))
    writable_check(defs, {"budget": 5, "unknown": 1}, ctx(defs, manage=True))  # admin
    with pytest.raises(ForbiddenError) as excinfo:
        writable_check(defs, {"budget": 5, "quota": 1, "severity": "low"}, ctx(defs))
    assert "budget, quota" in str(excinfo.value)
    assert "severity" not in str(excinfo.value)


# --- comment visibility gate (rides on the same permission union) ---


def test_internal_comments_require_the_permission():
    granted = frozenset({Permission.COMMENT_WRITE, Permission.COMMENT_READ_INTERNAL})
    ungranted = frozenset({Permission.COMMENT_WRITE})
    _check_internal(granted, CommentVisibility.INTERNAL)
    _check_internal(ungranted, CommentVisibility.PUBLIC)
    with pytest.raises(ForbiddenError):
        _check_internal(ungranted, CommentVisibility.INTERNAL)
