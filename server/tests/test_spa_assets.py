"""A missing build asset answers 404, never the SPA shell (RADD-1527).

Every release replaces the hashed bundle. A tab opened before it requests the
old hash on its next lazy route; `index.html` with a 200 failed to parse as a
module and stranded the user, where a 404 lets the page reload itself.
"""

from httpx import ASGITransport, AsyncClient

from radd.app import create_app
from radd.config import settings


async def test_a_missing_asset_is_404_and_a_route_is_still_the_shell(tmp_path, monkeypatch):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>shell</title>")
    (tmp_path / "assets" / "entry-abc123.js").write_text("export {};")
    monkeypatch.setattr(settings, "web_dist", str(tmp_path))

    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as http:
        present = await http.get("/assets/entry-abc123.js")
        assert present.status_code == 200 and "immutable" in present.headers["cache-control"]

        stale = await http.get("/assets/entry-OLDHASH.js")
        assert stale.status_code == 404, "an old chunk was answered with the shell"
        assert "text/html" not in stale.headers.get("content-type", "")

        # A client-side route is still the shell, revalidated on every load.
        route = await http.get("/issues/RADD-1")
        assert route.status_code == 200 and "shell" in route.text
        assert route.headers["cache-control"] == "no-cache"
