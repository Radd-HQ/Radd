"""The resource registry (spec 92) — the plugin extension point. A module registers each
protectable resource type with its access model and a `can_manage` hook; the generic
/grants router and the grants editor then work for it with no extra code."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

import uuid

from radd.kernel import registries
from radd.modules.auth.models import User

from .types import Access, GrantSubject

# (session, actor, resource_id, project_id) -> may the actor manage this resource's
# grants at that scope? project_id None = global / "can manage at all" (list). A
# resource that scopes authority per project (builtin fields, per-project managers)
# uses it; one whose authority is intrinsic (a custom field's own scope) ignores it.
CanManage = Callable[[AsyncSession, User, str, "uuid.UUID | None"], Awaitable[bool]]

# (session, resource_ids) -> {resource_id: display label} for the inspector
# (RADD-809). Only the owning module can turn a view id or field id into a name.
LabelFor = Callable[[AsyncSession, Sequence[str]], Awaitable[dict[str, str]]]
LockResource = Callable[[AsyncSession, str], Awaitable[None]]


@dataclass(frozen=True)
class ResourceSpec:
    resource_type: str
    can_manage: CanManage
    accesses: tuple[str, ...] = (Access.READ.value, Access.WRITE.value)
    # No in-scope grant of an access → is that access OPEN (fields) or CLOSED (views)?
    default_open: bool = True
    # Are `accesses` ordered levels (viewer<editor<owner) or independent flags (read/write)?
    hierarchical: bool = False
    subjects: tuple[GrantSubject, ...] = (
        GrantSubject.USER, GrantSubject.TEAM, GrantSubject.ROLE, GrantSubject.GROUP,
    )
    project_scoped: bool = True
    # For flag models: which OTHER accesses satisfy a given one (write implies read).
    implied_by: dict[str, tuple[str, ...]] = field(default_factory=dict)
    label: str = ""  # human name for the UI (defaults to resource_type)
    # Optional inspector hook (RADD-809): resolve resource ids to display names.
    # Absent = rows show the raw resource_id.
    label_for: LabelFor | None = None
    # Serialize ACL writes with the owner's sharing/transfer transaction. Reads
    # never acquire this lock; callers lock before checking mutable authority.
    lock_resource: LockResource | None = None
    roles_for: Callable[[AsyncSession, uuid.UUID, str], Awaitable[set[uuid.UUID]]] | None = None


# The store is the KERNEL registry (RADD-818): a plugin's resource types withdraw with it on disable.


def register_resource(spec: ResourceSpec) -> None:
    registries.access_resources[spec.resource_type] = spec


def get_spec(resource_type: str) -> ResourceSpec | None:
    spec = registries.access_resources.get(resource_type)
    return spec  # type: ignore[return-value]


def all_specs() -> list[ResourceSpec]:
    return list(registries.access_resources.values())  # type: ignore[arg-type]
