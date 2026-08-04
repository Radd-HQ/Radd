"""Per-key permission scopes (spec 113) — pure, so the intersection is testable.

An API key may carry LESS authority than the account behind it. The scope is
expressed in the same vocabulary as the roles matrix (raw permission atoms), and
enforcement is an intersection applied where permissions resolve, not a second
policy engine:

    effective = resolved(actor, project) ∩ scope(key, project)

A key can therefore never exceed its account: demote the account and every key it
holds narrows on the next request, with no key edit and no re-issuance.

`None` means UNSCOPED — the key carries the account's full authority, which is
what every personal access token did before this spec and still does.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field

from .types import Permission, qualify_permission, relation_meet, split_permission

GLOBAL_KEY = "global"
PROJECTS_KEY = "projects"


@dataclass(frozen=True)
class TokenScope:
    """What one key is allowed to do, before the account's own limits apply."""

    #: Atoms allowed at global scope (project=None resolutions).
    global_atoms: frozenset[Permission] = frozenset()
    #: project id -> atoms allowed in that project. A project absent from the map
    #: is not merely empty — the key cannot act in it at all.
    project_atoms: Mapping[uuid.UUID, frozenset[Permission]] = field(default_factory=dict)

    def allowed(self, project_id: uuid.UUID | None) -> frozenset[Permission]:
        if project_id is None:
            return self.global_atoms
        return frozenset(self.project_atoms.get(project_id, frozenset()))

    def narrow(
        self, permissions: frozenset[Permission], project_id: uuid.UUID | None
    ) -> frozenset[Permission]:
        """The intersection — LATTICE-AWARE since RADD-823. Two atoms with the
        same base meet at the NARROWER relation: an `item.read` key against an
        `item.read@team` account yields `@team` (the key cannot exceed the
        account), and an `item.read@team` key against an `item.read` account
        yields `@team` too (the account cannot exceed the key). With no
        relation qualifiers anywhere this is exactly the old set intersection.

        Global atoms also apply inside a project, because a global-scoped atom
        (page.read, timesheet.view) is checked with project=None in some paths
        and inside a project in others; a scope that granted it globally but
        not per project would behave differently depending on which code path
        asked, which is exactly the sort of subtlety a permission system must
        not have."""
        if project_id is None:
            allowed = self.global_atoms
        else:
            allowed = self.global_atoms | frozenset(
                self.project_atoms.get(project_id, frozenset())
            )
        return _lattice_intersect(permissions, allowed)

    def projects_allowing(self, permission: Permission) -> set[uuid.UUID]:
        """Which projects this scope permits `permission` in — the input to the
        MCP catalog's project enums (spec 114). Base-aware (RADD-823): a scope
        carrying `item.read@team` still ALLOWS item.read somewhere (narrowed),
        so the project stays in the catalog rather than vanishing."""
        wanted = str(permission)
        if any(split_permission(a)[0] == wanted for a in self.global_atoms):
            return set(self.project_atoms)  # a globally scoped atom applies everywhere named
        return {
            pid
            for pid, atoms in self.project_atoms.items()
            if any(split_permission(a)[0] == wanted for a in atoms)
        }

    def to_json(self) -> dict:
        return {
            GLOBAL_KEY: sorted(p.value for p in self.global_atoms),
            PROJECTS_KEY: {
                str(pid): sorted(p.value for p in atoms)
                for pid, atoms in self.project_atoms.items()
            },
        }


def _lattice_intersect(
    permissions: "frozenset[Permission] | frozenset[str]",
    allowed: "frozenset[Permission] | frozenset[str]",
) -> frozenset:
    """Per-base meet (RADD-823): for each held atom, the widest allowance of the
    same BASE narrows it to the lattice meet of the two relations. Incomparable
    relations grant nothing for that pair (fails closed). Pure and total; equal
    to plain set intersection when no atom carries a qualifier."""
    allowed_relations: dict[str, set[str]] = {}
    for atom in allowed:
        base, relation = split_permission(atom)
        allowed_relations.setdefault(base, set()).add(relation)
    out: set = set()
    for atom in permissions:
        base, held_rel = split_permission(atom)
        meets = {
            met
            for rel in allowed_relations.get(base, ())
            if (met := relation_meet(held_rel, rel)) is not None
        }
        for met in meets:
            out.add(atom if met == held_rel else qualify_permission(base, met))
    return frozenset(out)


def _atoms(values: object, where: str) -> frozenset[Permission]:
    if not isinstance(values, list):
        raise ValueError(f"scope {where} must be a list of permission atoms")
    out: set = set()
    for value in values:
        base, _relation = split_permission(str(value))
        try:
            Permission(base)
        except ValueError:
            # Refuse at WRITE time. An unknown atom that silently never matches is
            # a scope that looks granted and is not — the worst failure mode here.
            # (The relation qualifier is validated shallowly here — base only —
            # because a scope is written before the owning plugin's relations
            # may be loaded; an unregistered qualifier resolves to nothing,
            # which for a KEY is the fail-closed direction.)
            raise ValueError(f"unknown permission atom '{value}' in scope {where}") from None
        out.add(Permission(str(value)) if str(value) == base else str(value))
    return frozenset(out)


def parse_scope(raw: object) -> TokenScope | None:
    """`{"global": [atoms], "projects": {uuid: [atoms]}}` -> TokenScope. None = unscoped."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("scope must be an object")
    projects: dict[uuid.UUID, frozenset[Permission]] = {}
    for key, value in (raw.get(PROJECTS_KEY) or {}).items():
        try:
            project_id = uuid.UUID(str(key))
        except ValueError:
            raise ValueError(f"scope project key '{key}' is not a uuid") from None
        projects[project_id] = _atoms(value, f"projects.{key}")
    return TokenScope(
        global_atoms=_atoms(raw.get(GLOBAL_KEY) or [], "global"),
        project_atoms=projects,
    )
