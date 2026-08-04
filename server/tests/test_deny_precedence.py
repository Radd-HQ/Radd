"""Deny precedence (RADD-819), pure — every scope-pair case pinned.

The rule the resolver implements, written down: SPECIFICITY FIRST, DENY ON
TIES. A project-scoped row beats a global row regardless of effect; at equal
specificity a deny beats an allow. One deny row expresses "this team may not"
with nobody else's access touched — denies never flip a default-open resource
into restricted for non-matching subjects.
"""

import uuid
from dataclasses import dataclass

from radd.modules.access.registry import ResourceSpec
from radd.modules.access.resolution import (
    SubjectContext,
    effective_level,
    has_access,
    restricted_accesses,
)
from radd.modules.access.types import Access, GrantSubject

PROJECT = uuid.uuid4()
TEAM = uuid.uuid4()
OTHER_TEAM = uuid.uuid4()

SPEC = ResourceSpec(
    resource_type="t",
    can_manage=None,  # type: ignore[arg-type]
    implied_by={Access.READ.value: (Access.WRITE.value,)},
)
VIEW_SPEC = ResourceSpec(
    resource_type="v",
    can_manage=None,  # type: ignore[arg-type]
    accesses=("viewer", "editor", "owner"),
    hierarchical=True,
    default_open=False,
)


@dataclass(frozen=True)
class G:
    subject_type: str = GrantSubject.TEAM.value
    subject_id: uuid.UUID = TEAM
    access: str = Access.WRITE.value
    project_id: uuid.UUID | None = None
    effect: str = "allow"


def ctx(teams=(TEAM,)):
    return SubjectContext(user_id=uuid.uuid4(), team_ids=frozenset(teams), group_ids=frozenset())


def test_one_deny_row_is_the_whole_rule():
    """'Contractors cannot write Priority' — one row, nobody else touched."""
    grants = [G(effect="deny")]
    assert not has_access(grants, ctx(), Access.WRITE.value, None, SPEC)
    # A non-matching subject keeps the open default: the deny restricts its
    # SUBJECT, never the world.
    assert has_access(grants, ctx(teams=(OTHER_TEAM,)), Access.WRITE.value, None, SPEC)
    assert not restricted_accesses(grants, Access.WRITE.value, None)


def test_equal_scope_deny_beats_allow():
    grants = [G(effect="allow"), G(effect="deny")]
    assert not has_access(grants, ctx(), Access.WRITE.value, None, SPEC)
    scoped = [G(effect="allow", project_id=PROJECT), G(effect="deny", project_id=PROJECT)]
    assert not has_access(scoped, ctx(), Access.WRITE.value, PROJECT, SPEC)


def test_narrower_deny_beats_wider_allow():
    grants = [G(effect="allow"), G(effect="deny", project_id=PROJECT)]
    assert not has_access(grants, ctx(), Access.WRITE.value, PROJECT, SPEC)
    # Elsewhere the project deny is out of scope; the global allow stands.
    assert has_access(grants, ctx(), Access.WRITE.value, uuid.uuid4(), SPEC)


def test_narrower_allow_beats_wider_deny():
    """Specificity first: the project-scoped allow is the more deliberate
    statement and carves back the instance-wide deny — the written rule."""
    grants = [G(effect="deny"), G(effect="allow", project_id=PROJECT)]
    assert has_access(grants, ctx(), Access.WRITE.value, PROJECT, SPEC)
    # Where no narrower allow exists, the global deny holds.
    assert not has_access(grants, ctx(), Access.WRITE.value, uuid.uuid4(), SPEC)


def test_deny_write_does_not_touch_read():
    grants = [G(effect="deny")]  # deny WRITE
    assert has_access(grants, ctx(), Access.READ.value, None, SPEC)


def test_deny_on_the_implying_access_blocks_the_implied():
    """write implies read, so a read check is satisfied by write — and a deny
    of WRITE therefore blocks the write-implies-read route while an explicit
    read allowance still stands."""
    grants = [
        G(access=Access.READ.value, effect="allow"),
        G(access=Access.WRITE.value, effect="deny"),
    ]
    assert has_access(grants, ctx(), Access.READ.value, None, SPEC)
    assert not has_access(grants, ctx(), Access.WRITE.value, None, SPEC)


def test_hierarchical_deny_removes_the_level():
    grants = [
        G(access="editor", effect="allow"),
        G(access="viewer", effect="allow"),
        G(access="editor", effect="deny"),
    ]
    assert effective_level(grants, ctx(), None, VIEW_SPEC) == "viewer"
    assert effective_level([G(access="editor", effect="deny")], ctx(), None, VIEW_SPEC) is None
