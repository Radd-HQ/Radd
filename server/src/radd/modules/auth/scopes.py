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

from .types import Permission

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
        """The intersection. Global atoms also apply inside a project, because a
        global-scoped atom (page.read, timesheet.view) is checked with project=None
        in some paths and inside a project in others; a scope that granted it
        globally but not per project would behave differently depending on which
        code path asked, which is exactly the sort of subtlety a permission system
        must not have."""
        if project_id is None:
            return permissions & self.global_atoms
        return permissions & (self.global_atoms | frozenset(self.project_atoms.get(project_id, frozenset())))

    def projects_allowing(self, permission: Permission) -> set[uuid.UUID]:
        """Which projects this scope permits `permission` in — the input to the
        MCP catalog's project enums (spec 114)."""
        if permission in self.global_atoms:
            return set(self.project_atoms)  # a globally scoped atom applies everywhere named
        return {pid for pid, atoms in self.project_atoms.items() if permission in atoms}

    def to_json(self) -> dict:
        return {
            GLOBAL_KEY: sorted(p.value for p in self.global_atoms),
            PROJECTS_KEY: {
                str(pid): sorted(p.value for p in atoms)
                for pid, atoms in self.project_atoms.items()
            },
        }


def _atoms(values: object, where: str) -> frozenset[Permission]:
    if not isinstance(values, list):
        raise ValueError(f"scope {where} must be a list of permission atoms")
    out: set[Permission] = set()
    for value in values:
        try:
            out.add(Permission(value))
        except ValueError:
            # Refuse at WRITE time. An unknown atom that silently never matches is
            # a scope that looks granted and is not — the worst failure mode here.
            raise ValueError(f"unknown permission atom '{value}' in scope {where}") from None
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
