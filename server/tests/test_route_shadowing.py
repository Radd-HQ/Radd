"""A registered route must also be REACHABLE: Starlette matches in declaration
order, so a literal `/x/search` declared after `/x/{id}` answers a 422 about
parsing "search" (RADD-761). Checked over the ASSEMBLED app, walking
`effective_candidates()` through `_IncludedRouter` wrappers — their own `path` is
None, and a scan over `app.routes` passes vacuously (the first version did)."""

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
    """Every real route, in the order matching considers them: `_IncludedRouter`
    consults `effective_candidates()` (which may nest), and low-priority routes are
    appended after its own."""
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
    """No literal path may sit behind a parameter route of the same shape. No
    lifespan: `create_app` mounts every router itself, and a second set of startup
    hooks in one process made the suite hang about one run in three."""
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
