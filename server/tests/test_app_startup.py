"""The app must be able to start.

This file exists because 0.8.0 could not. RADD-745's cascade refactor wrote
`on_startup=_startup` where the field is `tuple[StartupHook, ...]`, the dataclass
stored the function unchanged, and `for hook in plugin.on_startup` raised
`TypeError: 'function' object is not iterable` inside `lifespan`. The image built,
published and deployed with 1391 green tests behind it, because nothing in the
suite had ever run the application's lifespan — so every startup hook in the
tree (the cascade consumer, the webhook dispatcher, the SLA engine, the LDAP
syncs) was unexercised by the tests that gate a release.

Two levels, deliberately:

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
    """A single value where a tuple is declared fails at CONSTRUCTION.

    Rejecting rather than normalising is the point: silently wrapping would make
    two shapes valid for one field, and the wrong one is what the next module
    would copy.
    """

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
    """Start and stop the real application, exactly as the container does.

    This is the assertion the release process was missing. Anything that raises
    in a plugin's `on_startup` fails here rather than in a rollout.

    The backup preflight is relaxed because it checks the ENVIRONMENT — the
    image ships `postgresql-client-16`, a developer's laptop usually does not,
    and a test that only passes where `pg_dump` happens to be installed would
    be turned off rather than fixed. Every plugin hook still runs for real.
    """
    monkeypatch.setattr(settings, "backup_tools_optional", True)
    app = create_app()
    async with app.router.lifespan_context(app):
        pass
