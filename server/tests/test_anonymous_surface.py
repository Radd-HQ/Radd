"""Spec 121 (RADD-1142): the anonymous surface is a FROZEN inventory.

An unauthenticated request resolves to the Anyone principal only on routes
that declare `Actor`; everything else keeps 401-ing. Two directions, both
asserted over the ASSEMBLED app (the `_IncludedRouter` walk from
test_route_shadowing):

* every route whose dependency graph reaches `auth.deps.actor` is in
  `ANONYMOUS_ROUTES` — a new route cannot join the surface by accident;
* every entry of `ANONYMOUS_ROUTES` really declares it — removing one is a
  visible edit here, not a silent regression.

And the seam is structurally read-only: `Actor` on a non-read method must
refuse before any handler runs.
"""

from radd.app import create_app
from radd.modules.auth.deps import actor

# (method, path) — the read surface a public project needs to render.
ANONYMOUS_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/api/v1/auth/me"),
        ("GET", "/api/v1/capabilities"),
        ("GET", "/api/v1/instance"),
        ("GET", "/api/v1/instance/status"),
        ("GET", "/api/v1/projects"),
        ("GET", "/api/v1/projects/summary"),
        ("GET", "/api/v1/projects/by-key/{key}"),
        ("GET", "/api/v1/projects/{project_id}"),
        ("GET", "/api/v1/items"),
        ("GET", "/api/v1/items/grouped"),  # read-only; same authorized ID scope
        ("GET", "/api/v1/items/slq/validate"),
        ("GET", "/api/v1/items/slq/suggest"),
        ("GET", "/api/v1/items/ids"),
        ("GET", "/api/v1/items/count"),
        ("GET", "/api/v1/items/by-key/{key}"),
        ("GET", "/api/v1/items/{item_id}"),
        ("GET", "/api/v1/items/{item_id}/history"),
        ("GET", "/api/v1/items/{item_id}/comments"),
        ("GET", "/api/v1/items/{entity_id}/comments/feed"),
        ("GET", "/api/v1/{entity_type}/{entity_id}/comments"),
        ("GET", "/api/v1/{entity_type}/{entity_id}/comments/feed"),
        # Replies are readable only through the root's live parent/audience gates.
        ("GET", "/api/v1/comments/{comment_id}/replies"),
        ("GET", "/api/v1/items/{item_id}/allowed-transitions"),
        ("GET", "/api/v1/items/{item_id}/web-links"),
        ("GET", "/api/v1/items/{item_id}/participants"),
        ("GET", "/api/v1/items/{item_id}/pages"),
        # RADD-1155: a public project's commits and pull requests are public.
        ("GET", "/api/v1/items/{item_id}/vcs-links"),
        ("GET", "/api/v1/attachments"),
        ("GET", "/api/v1/attachments/{attachment_id}"),
        # RADD-1295: a face beside a name a public visitor can already read.
        ("GET", "/api/v1/users/{user_id}/avatar"),
        ("GET", "/api/v1/views"),
        ("GET", "/api/v1/views/summary"),
        ("GET", "/api/v1/views/{view_id}"),
        ("GET", "/api/v1/states"),
        ("GET", "/api/v1/states/options"),
        ("GET", "/api/v1/state-categories"),
        ("GET", "/api/v1/labels"),
        ("GET", "/api/v1/issue-types"),
        ("GET", "/api/v1/issue-types/options"),
        ("GET", "/api/v1/fields"),
        ("GET", "/api/v1/fields/writable"),
        ("GET", "/api/v1/screens"),
        ("GET", "/api/v1/screens/effective"),
        ("GET", "/api/v1/cycles"),
        ("GET", "/api/v1/cycles/summary"),
        ("GET", "/api/v1/cycles/{cycle_id}"),
        ("GET", "/api/v1/releases"),
        ("GET", "/api/v1/releases/options"),
        ("GET", "/api/v1/releases/{release_id}"),
        ("GET", "/api/v1/scoped-settings/resolve"),
        ("GET", "/api/v1/projects/{project_id}/timelogging"),
        # The wiki (spec 121 §5): a public space is a grant, read through the
        # ordinary page routes.
        ("GET", "/api/v1/page-spaces"),
        ("GET", "/api/v1/page-spaces/summary"),
        ("GET", "/api/v1/page-spaces/by-identity/{identifier}"),
        ("GET", "/api/v1/page-spaces/{space_id}/pages"),
        ("GET", "/api/v1/pages/extensions"),
        # RADD-1233: a page is addressed by its PATH or its number.
        ("GET", "/api/v1/pages/by-path/{space_slug}/{path:path}"),
        ("GET", "/api/v1/pages/by-number/{number}"),
        ("GET", "/api/v1/pages/search"),
        ("GET", "/api/v1/pages/{page_id}"),
        ("GET", "/api/v1/pages/by-label/{name}"),
        ("GET", "/api/v1/pages/{page_id}/backlinks"),
        ("GET", "/api/v1/pages/{page_id}/items"),
        # Reports (RADD-1150): every report folds over `visible_matching_ids`,
        # the same row filter the lists use, so the world's numbers match the
        # world's list.
        ("GET", "/api/v1/reports/throughput"),
        ("GET", "/api/v1/reports/cumulative-flow"),
        ("GET", "/api/v1/reports/time-in-state"),
        ("GET", "/api/v1/reports/velocity"),
        ("GET", "/api/v1/reports/burnup"),
        ("GET", "/api/v1/reports/sla"),
        ("GET", "/api/v1/search"),
        ("GET", "/api/v1/search/deflect"),
        ("GET", "/api/v1/search/semantic"),
    }
)


def _flatten(routes):
    flat = []
    for route in routes:
        candidates = getattr(route, "effective_candidates", None)
        if callable(candidates):
            flat.extend(_flatten(candidates()))
            low = getattr(route, "effective_low_priority_routes", None)
            if callable(low):
                flat.extend(_flatten(low()))
            continue
        flat.append(route)
    return flat


def _reaches_actor(dependant) -> bool:
    if dependant.call is actor:
        return True
    return any(_reaches_actor(sub) for sub in dependant.dependencies)


def _actor_routes(app) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for route in _flatten(app.routes):
        # The walk yields FastAPI's effective-route wrappers, not APIRoute
        # itself; both carry `dependant` + `path` + `methods`, which is all
        # this needs (duck-typed on purpose — the wrapper class is private).
        dependant = getattr(route, "dependant", None)
        if dependant is None:
            continue
        if _reaches_actor(dependant):
            for method in route.methods or ():
                found.add((method, route.path))
    return found


def test_actor_inventory_is_exact():
    app = create_app()
    declared = _actor_routes(app)
    unlisted = declared - ANONYMOUS_ROUTES
    missing = ANONYMOUS_ROUTES - declared
    assert not unlisted, f"routes accept the anonymous actor but are not in the inventory: {sorted(unlisted)}"
    assert not missing, f"inventory names routes that no longer declare Actor: {sorted(missing)}"


def test_anonymous_surface_is_read_only():
    """No inventoried route is a write — the seam refuses anyway, but the
    inventory itself must never carry a mutation method."""
    assert {method for method, _ in ANONYMOUS_ROUTES} == {"GET"}


async def test_actor_refuses_a_write_from_the_principal():
    """A non-read method with no credential is refused at the seam before any
    handler — even on a route that declared Actor by mistake."""
    from types import SimpleNamespace

    from radd.exceptions import UnauthorizedError

    import pytest

    request = SimpleNamespace(method="POST", url=SimpleNamespace(path="/api/v1/items"))
    with pytest.raises(UnauthorizedError):
        await actor(request, session=None, user=None)
