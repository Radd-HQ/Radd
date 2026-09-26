"""The app must be able to start: 0.8.0 shipped with 1391 green tests and a
plugin whose `on_startup` was a bare function, because nothing ran the lifespan.

  - the *shape* check is fast and names the offending plugin and field;
  - the *lifespan* check is the real one — it runs what production runs.
"""

from collections.abc import Callable

import pytest

from radd.app import create_app
from radd.config import settings
from radd.kernel.plugin import RaddPlugin, _TUPLE_FIELDS
from radd.kernel.loader import load_plugins
from radd.modules.pluginmgr.boot import resolve_boot_paths


def test_every_plugin_declares_hooks_as_tuples():
    """The defect, stated as an assertion over the whole tree."""
    offenders = []
    for plugin in load_plugins(resolve_boot_paths()):
        for field in ("on_startup", "on_shutdown"):
            hooks = getattr(plugin, field)
            if not isinstance(hooks, tuple) or not all(callable(h) for h in hooks):
                offenders.append(f"{plugin.name}.{field} = {hooks!r}")
    assert not offenders, "hooks must be a tuple of callables: " + "; ".join(offenders)


def test_manifest_rejects_a_bare_contribution():
    """A single value where a tuple is declared fails at CONSTRUCTION. Rejecting
        rather than wrapping keeps one valid shape per field — the wrong one is what
        the next module would copy."""

    async def hook() -> None: ...

    with pytest.raises(TypeError, match=r"on_startup= must be a tuple"):
        RaddPlugin(name="broken", on_startup=hook)  # type: ignore[arg-type]

    # A str is iterable, so this one fails SILENTLY without the guard —
    # `depends_on="items"` becomes five one-character plugin names.
    with pytest.raises(TypeError, match=r"depends_on= must be a tuple"):
        RaddPlugin(name="broken", depends_on="items")  # type: ignore[arg-type]

    # The correct form still constructs, and the non-tuple fields are untouched.
    plugin = RaddPlugin(name="fine", on_startup=(hook,), cascades=lambda: ())
    assert plugin.on_startup == (hook,)
    assert isinstance(plugin.cascades, Callable)


def test_every_tuple_field_is_guarded():
    """The guard is derived from the annotations, not from a hand-kept list.

    If it were a list, a contribution added later would be unprotected and
    nobody would notice until the next crash-looping image.
    """
    declared = {f.name for f in RaddPlugin.__dataclass_fields__.values()
                if str(f.type).startswith("tuple[")}
    assert declared and declared == set(_TUPLE_FIELDS)


async def test_app_lifespan_completes(monkeypatch):
    """Start and stop the real application, as the container does; anything raising
        in an `on_startup` fails here, not in a rollout. The backup preflight is
        relaxed because it checks the ENVIRONMENT (`pg_dump` is in the image, rarely
        on a laptop); every plugin hook still runs for real."""
    monkeypatch.setattr(settings, "backup_tools_optional", True)
    app = create_app()
    async with app.router.lifespan_context(app):
        pass
