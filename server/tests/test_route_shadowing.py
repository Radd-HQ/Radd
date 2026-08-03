"""A registered route must also be REACHABLE.

This file exists because `/pages/search` was neither. RADD-701 moved page search
from `/docs/search` to `/pages/search` and left the declaration at the bottom of
`pages/router.py`, 190 lines below `@router.get("/pages/{page_id}")`. Starlette
matches in DECLARATION order, so every call was answered by the earlier route
with `page_id="search"` — a 422 about UUID parsing, from an endpoint the caller
never asked for.

Nothing caught it. The route imported, registered, and appeared in the OpenAPI
schema; `/docs` listed it; a reader of the source saw a perfectly ordinary
handler. Only calling it revealed anything, and no test called it (RADD-761).

The check is over the ASSEMBLED app rather than the source, because a module's
routes are mounted by its plugin at startup and the order that decides matching
is the order they end up in — not the order they are written in any one file.

Reaching them means walking through FastAPI's `_IncludedRouter` wrappers, which
is the same trap that once made plugin unmount a silent no-op: `include_router`
appends a wrapper whose own `path` is `None`, so a scan over `app.routes` sees
83 entries, almost all of them `None`, and finds nothing wrong with anything.
The first version of this test passed against the very bug it was written for.
"""

import re

from radd.app import create_app
from radd.config import settings

_PARAM = re.compile(r"\{([^}]+)\}")


def _segments(path: str) -> list[str]:
    """Path split into segments, each either a literal or `*` for a parameter."""
    return ["*" if _PARAM.fullmatch(s) else s for s in path.strip("/").split("/")]


def _is_greedy(path: str) -> bool:
    """A `{x:path}` converter spans separators — the SPA catch-all is one.

    It is *meant* to swallow whatever is left, so it is not a mistake; it just
    cannot participate in a same-shape comparison.
    """
    return any(":path" in m.group(1) for m in _PARAM.finditer(path))


def _flatten(routes) -> list[tuple[str, set[str]]]:
    """Every real route, in the order matching actually considers them.

    `_IncludedRouter` is a wrapper with no path of its own; `effective_candidates()`
    is what it consults, and it may hold further wrappers. Low-priority routes
    are appended after its own, which is where they are tried.
    """
    flat: list[tuple[str, set[str]]] = []
    for route in routes:
        candidates = getattr(route, "effective_candidates", None)
        if callable(candidates):
            flat.extend(_flatten(candidates()))
            low = getattr(route, "effective_low_priority_routes", None)
            if callable(low):
                flat.extend(_flatten(low()))
            continue
        path = getattr(route, "path", None)
        if path:
            flat.append((path, set(getattr(route, "methods", None) or ())))
    return flat


def shadowed(flat: list[tuple[str, set[str]]]) -> list[str]:
    """Which of these routes an earlier, more general one already answers."""
    routes = [
        (path, methods, _segments(path))
        for path, methods in flat
        if not _is_greedy(path)
    ]
    found = []
    for index, (path, methods, shape) in enumerate(routes):
        if all(part == "*" for part in shape):
            continue  # nothing concrete to be swallowed
        for earlier_path, earlier_methods, earlier in routes[:index]:
            if earlier_path == path or not (methods & earlier_methods):
                continue
            if len(earlier) != len(shape):
                continue
            covers = all(e == "*" or e == s for e, s in zip(earlier, shape))
            more_general = any(e == "*" and s != "*" for e, s in zip(earlier, shape))
            if covers and more_general:
                found.append(
                    f"{sorted(methods)} {path} is unreachable behind {earlier_path}"
                )
                break
    return found


def test_no_route_is_shadowed_by_an_earlier_pattern(monkeypatch):
    """No literal path may sit behind a parameter route of the same shape.

    No lifespan: `create_app` mounts every plugin's routers itself, so the table
    is complete before startup runs. Starting one anyway made the suite hang
    about one run in three — `test_app_startup` already runs the real lifespan,
    and a second set of startup hooks in the same process is a cost with nothing
    to buy.
    """
    monkeypatch.setattr(settings, "backup_tools_optional", True)
    flat = _flatten(create_app().routes)

    # The walk must reach the real API surface. Without this the wrapper trap
    # above returns ~80 paths that are all None, nothing is examined, and the
    # test reports success — which is exactly what the first version did.
    assert len(flat) > 400, f"route walk found only {len(flat)} routes"

    assert not shadowed(flat), "\n".join(shadowed(flat))


def test_the_detector_catches_the_shape_it_was_written_for():
    """A green whole-app assertion proves nothing until it can go red.

    Runs the real detector over RADD-761's exact arrangement, and over the fixed
    one, so a future edit that quietly neuters the check fails here.
    """
    broken = [("/pages/{page_id}", {"GET"}), ("/pages/search", {"GET"})]
    assert shadowed(broken) == [
        "['GET'] /pages/search is unreachable behind /pages/{page_id}"
    ]

    fixed = [("/pages/search", {"GET"}), ("/pages/{page_id}", {"GET"})]
    assert shadowed(fixed) == []

    # A different METHOD is not a shadow — POST /x/{id} cannot answer GET /x/y.
    assert shadowed([("/pages/{page_id}", {"POST"}), ("/pages/search", {"GET"})]) == []

    # Nor is a different SHAPE — the segment counts do not line up.
    assert shadowed([("/pages/{page_id}", {"GET"}), ("/pages/a/b", {"GET"})]) == []
