"""The plugin contract — `RaddPlugin`, the manifest of contributions.

Evolves the pre-kernel `RaddModule` (routers + lifecycle hooks) into a manifest
of *declarations* the loader aggregates into kernel registries
(docs/plugin-platform.md §4). All 49 builtin plugins construct `RaddPlugin`
directly; the migration is finished, so the `RaddModule` alias is gone. The
minimal `name=`/`description=`/`routers=` constructor still builds a valid
plugin with `core: true` and empty new fields (§11.1).
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, fields
from typing import Any, get_origin

from fastapi import APIRouter, Request, Response

from .specs import (
    CapabilitySpec,
    ConsumerSpec,
    CrudResourceSpec,
    EntitySpec,
    EventTypeSpec,
    IntegrationSpec,
    CascadeSpec,
    McpToolSpec,
    PageExtensionSpec,
    PermissionSpec,
    PluginUiManifest,
    SettingSectionSpec,
    SlqFieldSpec,
    TaskSpec,
    ViewTypeSpec,
    WidgetTypeSpec,
)

ExceptionHandler = Callable[[Request, Any], Response | Awaitable[Response]]
OpenApiAugmentor = Callable[[dict[str, Any]], None]
StartupHook = Callable[[], Awaitable[None]]

# The kernel SDK version plugins target (§9). Loader refuses an incompatible major.
KERNEL_API_VERSION = "1.0"


@dataclass(frozen=True)
class RaddPlugin:
    """A feature, declared. Identity + lifecycle + a manifest of contributions.

    `name` doubles as `id` when `id` is unset, so the minimal
    `RaddPlugin(name=…, description=…, routers=…)` form still constructs.
    """

    name: str
    description: str = ""

    # identity & lifecycle
    id: str = ""  # stable, e.g. "radd.slas"; defaults to `name`
    version: str = "0.0.0"
    api_version: str = KERNEL_API_VERSION
    core: bool = True  # reclassified builtins are core (non-disableable); externals set False
    depends_on: tuple[str, ...] = ()  # other plugin names that must load first
    # Per-plugin dependencies (§14): the Python distributions + npm packages this
    # plugin needs. Builtins map to optional-dependency extras (radd[ldap,ai,…]); the
    # install step resolves them. Declarative here so the manifest is the single
    # source of truth for what a plugin pulls in.
    python_deps: tuple[str, ...] = ()
    js_deps: tuple[str, ...] = ()

    # --- contributions (each → a kernel registry) ---
    routers: tuple[APIRouter, ...] = ()
    entities: tuple[EntitySpec, ...] = ()
    event_types: tuple[EventTypeSpec, ...] = ()
    consumers: tuple[ConsumerSpec, ...] = ()
    automation_actions: tuple[Any, ...] = ()
    automation_conditions: tuple[Any, ...] = ()
    tasks: tuple[TaskSpec, ...] = ()
    settings_keys: tuple[Any, ...] = ()
    settings_sections: tuple[SettingSectionSpec, ...] = ()
    permissions: tuple[PermissionSpec, ...] = ()
    crud_resources: tuple[CrudResourceSpec, ...] = ()
    access_resources: tuple[Any, ...] = ()
    capabilities: tuple[CapabilitySpec, ...] = ()
    slq_fields: tuple[SlqFieldSpec, ...] = ()  # custom SLQ query fields (e.g. `note ~ "x"`)
    view_types: tuple[ViewTypeSpec, ...] = ()  # custom saved-view types
    widget_types: tuple[WidgetTypeSpec, ...] = ()  # custom dashboard widget types
    mcp_tools: tuple[McpToolSpec, ...] = ()  # MCP tools (RADD-640; filtered + enforced by the kernel)
    page_extensions: tuple[PageExtensionSpec, ...] = ()  # page fenced blocks (RADD-709)
    #: Rows that die with a parent (RADD-745). A FACTORY, not a tuple: the set is
    #: derived from a binding registry that other modules populate at import
    #: time, so it cannot be evaluated when this manifest is constructed — and a
    #: static tuple would also not survive the registry being cleared and
    #: rebuilt, which the app lifespan does.
    cascades: Callable[[], tuple[CascadeSpec, ...]] | None = None
    integrations: tuple[IntegrationSpec, ...] = ()
    ui: PluginUiManifest | None = None

    # kept from the pre-kernel module contract
    exception_handlers: tuple[tuple[type[Exception], ExceptionHandler], ...] = ()
    openapi_augmentors: tuple[OpenApiAugmentor, ...] = ()
    on_startup: tuple[StartupHook, ...] = ()
    on_shutdown: tuple[StartupHook, ...] = ()

    def __post_init__(self) -> None:
        if not self.id:
            object.__setattr__(self, "id", self.name)
        self._reject_unwrapped_contributions()

    def _reject_unwrapped_contributions(self) -> None:
        """Refuse a single contribution passed where a tuple is declared.

        Every contribution field on this manifest is a `tuple[Spec, ...]`, and
        `on_startup=_startup` instead of `on_startup=(_startup,)` is a defect
        Python will not catch: the dataclass stores whatever it is handed, and
        the failure surfaces much later, wherever the field is finally iterated.
        RADD-745's cascade refactor shipped exactly that and produced an image
        that could not complete `lifespan` — a one-character typo that reached a
        published container with 1391 green tests behind it.

        Rejecting rather than NORMALISING is the deliberate choice. Quietly
        wrapping a bare value into a 1-tuple would make two shapes valid for one
        field, and the second one is how the next module learns the wrong
        convention. This raises at import — before an image is built, let alone
        deployed.

        A `str` is caught by the same rule and matters just as much: it *is*
        iterable, so `depends_on="items"` becomes five one-character dependency
        names rather than one, with no error anywhere.
        """
        for name in _TUPLE_FIELDS:
            value = getattr(self, name)
            if isinstance(value, tuple):
                continue
            raise TypeError(
                f"RaddPlugin({self.name!r}): {name}= must be a tuple, got "
                f"{type(value).__name__}. Write {name}=(<value>,) — a single "
                "contribution still needs the trailing comma."
            )


def _tuple_fields() -> tuple[str, ...]:
    """The fields the check policices, read from the dataclass's own annotations.

    Derived rather than listed by hand: a new `tuple[…]` contribution is covered
    the moment it is declared, which a maintained list would not be. Both
    annotation forms are handled because whether `field.type` is a string
    depends on PEP 563 being on in this module — a detail that should not decide
    whether the guard works.
    """
    names = []
    for field in fields(RaddPlugin):
        declared = field.type
        is_tuple = (
            declared.startswith("tuple[")
            if isinstance(declared, str)
            else get_origin(declared) is tuple
        )
        if is_tuple:
            names.append(field.name)
    return tuple(names)


_TUPLE_FIELDS: tuple[str, ...] = _tuple_fields()

