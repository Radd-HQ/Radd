"""Host services the kernel's entity machinery resolves at runtime (RADD-892).

Identity, the permission gate, row visibility and event emission are policies, so
`kernel/entities.py` asks the installed `EntityHost` (auth provides it) at REQUEST time,
never at build time: the routers are built while plugins load, and reload moves that
instant. The slot lives outside `KernelRegistries` because `clear()` would wipe it.
"""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class EntityHost(Protocol):
    """What the generated entity CRUD needs from the platform.

    Four operations, because those are the four decisions the kernel must not
    make: identity, the gate, row visibility, and where an event goes.
    """

    async def current_user(self, request: Any, session: Any) -> Any:
        """The acting user, or raise — the kernel's routers depend on this, so it
        must have a fixed (request, session) signature FastAPI can satisfy."""
        ...

    async def require(
        self, session: Any, user: Any, atom: str, *, project_id: Any | None
    ) -> None:
        """Refuse unless the user holds `atom` (on `project_id` when given)."""
        ...

    async def visible_rows(
        self, session: Any, user: Any, entity_key: str, rows: list[Any]
    ) -> list[Any]:
        """Narrow project-scoped rows to the ones this user may read."""
        ...

    async def readable_project_ids(self, session: Any, user: Any, entity_key: str) -> list[Any]:
        """Projects with potential read access, before search pagination."""
        ...

    async def emit(
        self,
        session: Any,
        *,
        event_type: str,
        entity_type: str,
        entity_id: Any,
        actor_id: Any,
        payload: dict[str, Any] | None = None,
        subjects: dict[str, Any] | None = None,
        changes: list[dict[str, Any]] | None = None,
    ) -> None: ...


_entity_host: EntityHost | None = None


def set_entity_host(host: EntityHost) -> None:
    """Install the host. Called once, at the providing plugin's import."""
    global _entity_host
    _entity_host = host


def entity_host() -> EntityHost:
    if _entity_host is None:
        raise RuntimeError(
            "no EntityHost installed — a plugin declaring entities needs the "
            "plugin that provides identity/authz/events loaded first "
            "(depends_on=('auth', ...))"
        )
    return _entity_host
