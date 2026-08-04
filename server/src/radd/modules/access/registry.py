"""The resource registry (spec 92) — the plugin extension point.

A module registers each protectable resource type with its access model (which
access values exist, whether absence-of-grants means open or closed, whether the
values are independent flags or ordered levels, which subject kinds apply, whether
grants can be project-scoped) and an authz hook deciding who may manage its grants.
The generic /grants router and the reusable GrantsEditor then work for it with no
extra code — including for plugins.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

import uuid

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


# RADD-818: the store is the KERNEL registry, not a private dict — the
# sixteenth contribution kind. A plugin declares `access_resources=` on its
# manifest (or calls the SDK's register_access_resource, which lands here),
# and disable withdraws its resource types with everything else it
# contributed. Core modules keep calling register_resource at import; the
# app loader re-registers manifests after clear(), so both paths converge.


def register_resource(spec: ResourceSpec) -> None:
    from radd.kernel.registry import registries

    registries.access_resources[spec.resource_type] = spec


def get_spec(resource_type: str) -> ResourceSpec | None:
    from radd.kernel.registry import registries

    spec = registries.access_resources.get(resource_type)
    return spec  # type: ignore[return-value]


def all_specs() -> list[ResourceSpec]:
    from radd.kernel.registry import registries

    return list(registries.access_resources.values())  # type: ignore[arg-type]
