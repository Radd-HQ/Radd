"""Host services the kernel's generic machinery resolves at runtime (RADD-892).

The kernel is mechanism. `kernel/entities.py` turns an `EntitySpec` into a table,
a pydantic trio and a CRUD router with no plugin code — but it cannot decide who
the caller is, whether they may act, which rows they may see, or where an event
goes. Those are policies, and policies belong to plugins.

Until RADD-892 the generated handlers reached for them with deferred
`from radd.modules.auth import authz` / `projects` / `events` imports, which made
the kernel depend on three plugins it is supposed to sit underneath. One protocol
instead, implemented by the plugin that already owns every policy in it (auth,
which reaches projects and events through its own declared dependencies).

**Resolved at REQUEST time, never captured.** The entity routers are built while
plugins are still loading, so a handler that bound the host at build time would
capture whatever happened to be installed at that instant — and in the reload
path (`registries.clear()` + re-register) that instant moves. The slot lives
here rather than in `KernelRegistries` for the mirror-image reason: it is
installed once at module import, and `clear()` would wipe it with nothing to
re-run.
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

    async def emit(
        self,
        session: Any,
        *,
        event_type: str,
        entity_type: str,
        entity_id: Any,
        actor_id: Any,
        payload: dict[str, Any],
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
