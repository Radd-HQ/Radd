"""Per-key permission scopes (spec 113) — pure. A key may carry LESS than its
account; enforcement is `resolved ∩ scope`, applied where permissions resolve,
so a key can never exceed its account. `None` = unscoped (full authority)."""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field

from .types import (
    Permission,
    all_permission_keys,
    qualify_permission,
    relation_meet,
    split_permission,
)

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
        """The intersection, lattice-aware (RADD-823): the same base meets at the
        NARROWER relation. Global atoms apply inside a project too — some paths
        check a global atom with project=None and others inside a project."""
        if project_id is None:
            allowed = self.global_atoms
        else:
            allowed = self.global_atoms | frozenset(
                self.project_atoms.get(project_id, frozenset())
            )
        return _lattice_intersect(permissions, allowed)

    def to_json(self) -> dict:
        # `str(...)`, not `.value`: an atom may be a registry-contributed string
        # rather than an enum member (RADD-890), and a relation-qualified atom
        # never was one.
        return {
            GLOBAL_KEY: sorted(str(p) for p in self.global_atoms),
            PROJECTS_KEY: {
                str(pid): sorted(str(p) for p in atoms)
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
    # RADD-890: the LIVE catalog, the same set the role editor validates against.
    known = all_permission_keys()
    out: set = set()
    for value in values:
        base, _relation = split_permission(str(value))
        if base not in known:
            # Refuse at WRITE time: an unknown atom never matches, so it would look
            # granted and not be. The qualifier is checked shallowly (base only) —
            # an unregistered one resolves to nothing, which for a KEY fails closed.
            raise ValueError(f"unknown permission atom '{value}' in scope {where}")
        out.add(_atom(str(value), base))
    return frozenset(out)


def _atom(value: str, base: str) -> "Permission | str":
    """The enum member when there is one (so `.value`/identity keep working at
    the ~1000 call sites that hold them), the raw string otherwise."""
    if value != base:
        return value  # relation-qualified: never an enum member
    try:
        return Permission(value)
    except ValueError:
        return value


def parse_scope(raw: object) -> TokenScope | None:
    """`{"global": [atoms], "projects": {uuid: [atoms]}}` -> TokenScope. None = unscoped."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("scope must be an object")
    projects: dict[uuid.UUID, frozenset[Permission]] = {}
    project_values = raw.get(PROJECTS_KEY)
    if project_values is None:
        project_values = {}
    if not isinstance(project_values, dict):
        raise ValueError("scope projects must be an object keyed by project UUID")
    for key, value in project_values.items():
        try:
            project_id = uuid.UUID(str(key))
        except ValueError:
            raise ValueError(f"scope project key '{key}' is not a uuid") from None
        projects[project_id] = _atoms(value, f"projects.{key}")
    return TokenScope(
        global_atoms=_atoms(raw.get(GLOBAL_KEY) if raw.get(GLOBAL_KEY) is not None else [], "global"),
        project_atoms=projects,
    )
