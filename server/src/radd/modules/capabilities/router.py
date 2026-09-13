import os
from pathlib import Path

from fastapi import APIRouter

from radd.kernel import capabilities as kcaps
from radd.kernel import registries
from radd.modules.auth.deps import Actor

from .schemas import (
    CapabilitiesRead,
    CapabilityRead,
    NavItemRead,
    PluginRemoteRead,
    TypeOptionRead,
)


def _versioned_remote(name: str, remote: str) -> str:
    """Append a build-version query (`?v=<mtime>`) to a remote's url so a REBUILT bundle is fetched
    fresh — the url is otherwise stable, so a browser (and the ES module map within a session) would
    keep the old build. The mtime of the served file changes on every `build-all`."""
    ui_dir = registries.plugin_ui_dirs.get(name)
    if ui_dir:
        try:
            mtime = int(os.path.getmtime(Path(ui_dir) / Path(remote).name))
            return f"{remote}?v={mtime}"
        except OSError:
            pass
    return remote

router = APIRouter(tags=["capabilities"])


@router.get("/capabilities", response_model=CapabilitiesRead)
async def get_capabilities(user: Actor) -> CapabilitiesRead:
    """The backend-assembled UI manifest (docs/plugin-platform.md §3.2/§8a).

    `capabilities`: each enabled plugin's `CapabilitySpec` evaluated (its `check()`),
    replacing the hardcoded provider enumeration `/instance/status` inlined
    (chokepoint 2). `nav`: plugin-contributed nav items (chokepoint 3) — the SPA
    renders them alongside its builtin nav, gating each by `requires` against the
    user's atoms, so an enabled plugin's nav appears with no edit to the shell.
    Authenticated. The pre-sign-in subset stays on `/instance/login-options`.
    """
    return CapabilitiesRead(
        capabilities=[CapabilityRead(**c) for c in kcaps.evaluate()],
        nav=[
            NavItemRead(
                key=n.key, label=n.label, path=n.path, icon=n.icon,
                section=n.section, requires=list(n.requires),
                capability=n.capability, order=n.order,
            )
            for n in sorted(registries.nav, key=lambda n: (n.order, n.label))
        ],
        # Every enabled plugin's name — disabling a plugin unregisters it here, so
        # the SPA can hide its UI. Use the plugin `name` (the stable enable key that
        # depends_on / the frontend gate keys on), not the dotted id.
        plugins=sorted(p.name for p in registries.plugins.values()),
        # Federated UI remotes (spec 94): every enabled plugin that ships a UI bundle. The host
        # imports each `remote_entry` and version-gates on `ui_api_version`. Disabling a plugin
        # unregisters it from `registries.plugins`, so it drops out here and the host unmounts it.
        remotes=sorted(
            (
                PluginRemoteRead(
                    name=p.name,
                    remote_entry=_versioned_remote(p.name, p.ui.remote),
                    ui_api_version=p.ui.ui_api_version or "1.0.0",
                )
                for p in registries.plugins.values()
                if p.ui is not None and p.ui.remote
            ),
            key=lambda r: r.name,
        ),
        view_types=[
            TypeOptionRead(key=v.key, label=v.label)
            for v in sorted(registries.view_types.values(), key=lambda v: v.label)
        ],
        widget_types=[
            TypeOptionRead(key=w.key, label=w.label)
            for w in sorted(registries.widget_types.values(), key=lambda w: w.label)
        ],
    )
