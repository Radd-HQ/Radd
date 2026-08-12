"""The SBOM page's pure half, and the one thing it refuses to do (RADD-1065).

`scripts/sbom_page.py` runs in CI at tag time over two CycloneDX documents that
no test here produces, so what is pinned is the READING: which section a
component lands in, what its licence column says given the three shapes
CycloneDX allows, and which components are not packages at all.

Two of these are about a number a reader would trust: the counts in the header
must be the counts in the tables (they are computed from the same grouping), and
a package catalogued at six paths must be one row, not six — the real 0.32.0
image lists every Python package twice (once in `/opt/venv`, once in uv's cache
layer), so an un-deduped page would claim 138 Python dependencies where 73 ship.

The publish half is covered at its only decision: the page hangs off the
version's release-notes page or it is not published at all.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import release_notes  # noqa: E402
import sbom_page  # noqa: E402
from sbom_page import Package, collect, license_of, main, render, tools  # noqa: E402


def _component(name, version="1.0.0", purl=None, licenses=None):
    component = {"name": name, "version": version}
    if purl is not None:
        component["purl"] = purl
    if licenses is not None:
        component["licenses"] = licenses
    return component


def _doc(*components, tool="syft", tool_version="1.51.0"):
    return {
        "metadata": {"tools": {"components": [{"name": tool, "version": tool_version}]}},
        "components": list(components),
    }


# --- which section a component lands in -----------------------------------------


@pytest.mark.parametrize(
    "purl, section",
    [
        ("pkg:deb/debian/libpq5@17.10", "Debian packages"),
        ("pkg:pypi/fastapi@0.139.2", "Python packages"),
        ("pkg:npm/react@19.2.7", "npm packages"),
        ("pkg:cargo/serde@1.0.0", "Rust crates"),
        # A purl type nothing here claims, and the empty string a component with
        # no purl carries: listed, never dropped. An SBOM that silently omits is
        # worse than one that says "Other".
        ("pkg:generic/python@3.12.13", "Other"),
        ("", "Other"),
    ],
)
def test_the_ecosystem_comes_from_the_purl(purl, section):
    groups = collect([_doc(_component("thing", purl=purl or None))])
    assert list(groups) == [section]


def test_sections_are_ordered_and_sorted_case_insensitively():
    groups = collect(
        [
            _doc(
                _component("Zope", purl="pkg:pypi/Zope@5.0"),
                _component("alembic", purl="pkg:pypi/alembic@1.18.5"),
                _component("react", purl="pkg:npm/react@19.2.7"),
                _component("libpq5", purl="pkg:deb/debian/libpq5@17.10"),
            )
        ]
    )
    assert list(groups) == ["Debian packages", "Python packages", "npm packages"]
    assert [p.name for p in groups["Python packages"]] == ["alembic", "Zope"]


# --- the licence column ----------------------------------------------------------


@pytest.mark.parametrize(
    "licenses, expected",
    [
        # The three shapes CycloneDX allows, all one column: a reader wants the
        # terms, not which slot the generator used.
        ([{"license": {"id": "MIT"}}], "MIT"),
        ([{"license": {"name": "PostgreSQL"}}], "PostgreSQL"),
        ([{"expression": "Apache-2.0 OR BSD-3-Clause"}], "Apache-2.0 OR BSD-3-Clause"),
        ([{"license": {"id": "GPL-2.0-only"}}, {"license": {"id": "MIT"}}], "GPL-2.0-only, MIT"),
        # id wins over a name repeating it, and a repeat is listed once.
        ([{"license": {"id": "MIT", "name": "MIT License"}}, {"license": {"id": "MIT"}}], "MIT"),
        # Nothing to say, said as nothing — never "unknown", which would read as
        # a claim the document did not make.
        ([], ""),
        ([{"license": {}}], ""),
        (None, ""),
    ],
)
def test_every_licence_shape_becomes_one_string(licenses, expected):
    assert license_of(_component("x", licenses=licenses)) == expected


# --- what is a package, and what is only a row -----------------------------------


def test_a_component_with_neither_purl_nor_version_is_not_a_package():
    """syft's per-file residue: a classifier match with nothing to identify it.
    A version alone is enough to stay (the image's own `debian 13.6` is real)."""
    groups = collect(
        [
            {
                "components": [
                    _component("mystery", version="", purl=None),
                    _component("debian", version="13.6", purl=None),
                ]
            }
        ]
    )
    assert [p.name for p in groups["Other"]] == ["debian"]


def test_the_same_package_at_two_paths_is_one_row():
    groups = collect(
        [
            _doc(
                _component("alembic", "1.18.5", "pkg:pypi/alembic@1.18.5"),
                _component("alembic", "1.18.5", "pkg:pypi/alembic@1.18.5"),
                # A different version is a different package.
                _component("alembic", "1.18.4", "pkg:pypi/alembic@1.18.4"),
            )
        ]
    )
    assert groups["Python packages"] == [
        Package("alembic", "1.18.4", ""),
        Package("alembic", "1.18.5", ""),
    ]


def test_a_duplicate_supplies_the_licence_the_first_copy_lacked():
    """The two documents overlap (the image carries the built plugin bundles the
    lockfile also names) and syft licences a package from whatever metadata it
    read — so the second copy can know terms the first did not."""
    groups = collect(
        [
            _doc(_component("@radd-plugin-ui/csat", "1.0.0", "pkg:npm/%40radd-plugin-ui/csat@1.0.0")),
            _doc(
                _component(
                    "@radd-plugin-ui/csat",
                    "1.0.0",
                    "pkg:npm/%40radd-plugin-ui/csat@1.0.0",
                    [{"license": {"id": "MIT"}}],
                )
            ),
        ]
    )
    assert groups["npm packages"] == [Package("@radd-plugin-ui/csat", "1.0.0", "MIT")]


# --- who catalogued it -----------------------------------------------------------


def test_the_tool_is_read_from_the_documents_not_hardcoded():
    assert tools([_doc(), _doc()]) == ["syft 1.51.0"]
    assert tools([_doc(), _doc(tool_version="1.52.0")]) == ["syft 1.51.0", "syft 1.52.0"]
    # CycloneDX before 1.5 makes `tools` a bare list.
    assert tools([{"metadata": {"tools": [{"name": "cdxgen", "version": "10.0.0"}]}}]) == [
        "cdxgen 10.0.0"
    ]
    assert tools([{"metadata": {}}]) == []


# --- the rendered page -----------------------------------------------------------


def _rendered(*documents):
    groups = collect(documents)
    return render(
        "0.32.0",
        groups,
        tools(documents),
        ["radd-0.32.0-image.cdx.json", "radd-0.32.0-web.cdx.json"],
        "v0.32.0",
        "https://git.radd-hq.com/Radd/Radd",
    )


def test_the_header_counts_are_the_table_counts():
    body = _rendered(
        _doc(
            _component("react", "19.2.7", "pkg:npm/react@19.2.7"),
            _component("react-dom", "19.2.7", "pkg:npm/react-dom@19.2.7"),
            _component("fastapi", "0.139.2", "pkg:pypi/fastapi@0.139.2"),
            # Deduped away — and therefore not counted anywhere.
            _component("fastapi", "0.139.2", "pkg:pypi/fastapi@0.139.2"),
        )
    )
    assert "1073 components" not in body
    assert "3 components" in body
    assert "| Python packages | 1 |" in body and "| npm packages | 2 |" in body
    assert "| **Total** | **3** |" in body
    assert "## npm packages (2)" in body
    assert body.count("| `react") == 2


def test_the_page_says_where_the_documents_are():
    body = _rendered(_doc(_component("react", "19.2.7", "pkg:npm/react@19.2.7")))
    assert "https://git.radd-hq.com/Radd/Radd/releases/tag/v0.32.0" in body
    assert (
        "[radd-0.32.0-web.cdx.json](https://git.radd-hq.com/Radd/Radd/releases/download/"
        "v0.32.0/radd-0.32.0-web.cdx.json)" in body
    )
    assert "`syft 1.51.0`" in body


def test_a_pipe_in_a_licence_cannot_break_the_table():
    """GFM ends a cell at an unescaped pipe — inside a code span too. One
    Debian licence field in the real 0.32.0 SBOM is a bare sha256, so this
    column carries whatever the document says, not what we hoped it says."""
    body = _rendered(
        _doc(
            _component(
                "weird",
                "1.0",
                "pkg:deb/debian/weird@1.0",
                [{"expression": "MIT | Apache-2.0"}],
            )
        )
    )
    row = next(line for line in body.splitlines() if line.startswith("| `weird`"))
    assert row == "| `weird` | `1.0` | MIT \\| Apache-2.0 |"
    assert len(row.replace("\\|", "").split("|")) == 5


def test_the_body_is_html_free():
    """Radd's viewer is CommonMark and prints raw HTML literally (RADD-942)."""
    assert "<" not in _rendered(_doc(_component("react", "19.2.7", "pkg:npm/react@19.2.7")))


# --- publishing: the one refusal -------------------------------------------------


SPACE = {"id": "sp1", "slug": "radd", "name": "Radd"}
ROOT = {"id": "p-root", "title": "Radd Documentation", "parent_id": None}
SECTION = {"id": "p-notes", "title": "Release notes", "parent_id": "p-root"}
VERSION = {"id": "p-0320", "title": "0.32.0", "parent_id": "p-notes"}


class _Wiki:
    """The Pages endpoints publishing touches, and nothing else — an unexpected
    call is a failed assertion rather than a silent success."""

    def __init__(self, spaces, pages):
        self.spaces = spaces
        self.pages = pages
        self.created: list[dict] = []
        self.patched: list[tuple[str, dict]] = []

    def __call__(self, url, token, method="GET", body=None):
        path = url.split("/api/v1/")[1]
        if path == "page-spaces":
            return self.spaces
        if path.endswith("/pages") and path.startswith("page-spaces/"):
            return self.pages
        if path == "pages" and method == "POST":
            self.created.append(body)
            return {"id": "p-new", "slug": "sbom-0-32-0"}
        if path.startswith("pages/"):
            page_id = path.split("/")[1]
            if method == "PATCH":
                self.patched.append((page_id, body))
                return {"id": page_id, "slug": "sbom-0-32-0"}
            return next(p for p in self.pages if p["id"] == page_id)
        raise AssertionError(f"unexpected call: {method} {url}")


@pytest.fixture
def documents(tmp_path):
    doc = _doc(_component("react", "19.2.7", "pkg:npm/react@19.2.7"))
    paths = []
    for name in ("radd-0.32.0-image.cdx.json", "radd-0.32.0-web.cdx.json"):
        path = tmp_path / name
        path.write_text(json.dumps(doc))
        paths.append(str(path))
    return paths


def _wire(monkeypatch, wiki):
    monkeypatch.setenv("RADD_API_TOKEN", "pat")
    monkeypatch.setattr(sbom_page, "_request", wiki)
    monkeypatch.setattr(release_notes, "_request", wiki)


def test_the_page_is_filed_under_the_version_it_describes(monkeypatch, documents, capsys):
    wiki = _Wiki([SPACE], [ROOT, SECTION, VERSION])
    _wire(monkeypatch, wiki)

    assert main(["--tag", "v0.32.0", *documents]) == 0
    assert len(wiki.created) == 1
    created = wiki.created[0]
    assert created["space_id"] == "sp1"
    assert created["title"] == "SBOM 0.32.0"
    assert created["parent_id"] == "p-0320"
    assert "## npm packages (1)" in created["body"]
    assert "page:" in capsys.readouterr().out


def test_republishing_a_version_updates_its_page(monkeypatch, documents):
    """Title is the identity (release_notes.py's rule): a workflow_dispatch
    rebuild refreshes the SBOM instead of growing a second one."""
    existing = {"id": "p-sbom", "title": "SBOM 0.32.0", "parent_id": "p-0320", "body": "stale"}
    wiki = _Wiki([SPACE], [ROOT, SECTION, VERSION, existing])
    _wire(monkeypatch, wiki)

    assert main(["--tag", "v0.32.0", *documents]) == 0
    assert wiki.created == []
    assert [page_id for page_id, _ in wiki.patched] == ["p-sbom"]


@pytest.mark.parametrize(
    "spaces, pages, says",
    [
        # The space was never created — so neither was anything under it.
        ([], [ROOT, SECTION, VERSION], "no 'Radd' space"),
        ([SPACE], [ROOT], "Release notes"),                  # the changelog step never ran
        ([SPACE], [ROOT, SECTION], "no '0.32.0' page"),      # this version's notes are missing
        # A same-titled page somewhere else is NOT the parent.
        (
            [SPACE],
            [ROOT, SECTION, {"id": "x", "title": "0.32.0", "parent_id": None}],
            "no '0.32.0' page",
        ),
    ],
)
def test_without_the_release_notes_page_nothing_is_published(
    monkeypatch, documents, capsys, spaces, pages, says
):
    """The SBOM belongs beside the version's notes. Filing it anywhere else
    would hide it, so the step goes red instead — which is safe, because the
    workflow marks it continue-on-error and the image is already pushed."""
    wiki = _Wiki(spaces, pages)
    _wire(monkeypatch, wiki)

    assert main(["--tag", "v0.32.0", *documents]) == 1
    assert wiki.created == [] and wiki.patched == []
    # The message names what is missing: a red step nobody can act on is noise.
    assert says in capsys.readouterr().err


def test_a_document_that_lists_nothing_is_a_failure_not_an_empty_page(
    monkeypatch, tmp_path, capsys
):
    """An empty bill of materials is indistinguishable from a broken scanner,
    and publishing one would replace a good page with a lie."""
    path = tmp_path / "empty.cdx.json"
    path.write_text(json.dumps({"metadata": {}, "components": []}))
    wiki = _Wiki([SPACE], [ROOT, SECTION, VERSION])
    _wire(monkeypatch, wiki)

    assert main(["--tag", "v0.32.0", str(path)]) == 1
    assert wiki.created == []
    assert "no components" in capsys.readouterr().err
