#!/usr/bin/env python3
"""Publish a version's bill of materials as a readable wiki page (RADD-1065).

RADD-1026 already attaches two CycloneDX documents to every Forgejo release.
A `.cdx.json` is a machine artifact: answering "does 0.32.0 still ship that
crate?" means downloading a 1.4 MB file and writing a jq expression. This
renders the same two documents as ONE markdown page in the wiki, beside the
release notes, so the answer is a page load and a browser find.

The page hangs off the version's release-notes page, which `release_notes.py`
creates:

    Space:  Radd
      Page: Radd Documentation
        Page: Release notes
          Page: 0.32.0        <- the changelog
            Page: SBOM 0.32.0 <- this

That parent is REQUIRED, never created here: a version's SBOM belongs to the
version's notes, and a page filed anywhere else is one nobody would find. When
it is missing this says so and exits non-zero — the workflow step is
continue-on-error, so the gap shows up as a red step on a good release.

A component's ecosystem is read from its purl (`pkg:deb/`, `pkg:pypi/`,
`pkg:npm/`, `pkg:cargo/`), which is the CycloneDX-standard identity, rather than
from syft's own `syft:package:type` properties, which are the generator's
vocabulary and would tie the page to one tool.

Usage:
    sbom_page.py --tag v0.32.0 radd-0.32.0-image.cdx.json radd-0.32.0-web.cdx.json
    sbom_page.py --tag v0.32.0 --dry-run *.cdx.json    # print the body, publish nothing

Environment:
    RADD_BASE_URL        default https://project.radd-hq.com
    RADD_API_TOKEN       PAT with page.write
    Asset links point at the git host chosen by release_host.py (GitHub inside
    GitHub Actions, Forgejo otherwise).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
from collections.abc import Iterable
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import release_host  # noqa: E402
from release_notes import (  # noqa: E402
    ROOT_PAGE,
    SECTION_PAGE,
    SPACE_NAME,
    SPACE_SLUG,
    _find_or_create_page,
    _request,
)

#: purl type -> the section it is listed under, in reading order. Anything else
#: lands in `OTHER` rather than being dropped: an unrecognised purl is still a
#: thing that ships, and a silent omission is the one failure an SBOM cannot
#: afford.
ECOSYSTEMS: list[tuple[str, str]] = [
    ("deb", "Debian packages"),
    ("pypi", "Python packages"),
    ("npm", "npm packages"),
    ("cargo", "Rust crates"),
]
OTHER = "Other"
SECTION_ORDER: list[str] = [label for _, label in ECOSYSTEMS] + [OTHER]

#: The page's title, and therefore its identity — `_find_or_create_page` matches
#: on (parent, title), so re-running a version updates its SBOM page.
TITLE_PREFIX = "SBOM "


class MissingParent(Exception):
    """The version's release-notes page is not there to hang the SBOM off."""


@dataclass(frozen=True)
class Package:
    name: str
    version: str
    license: str


# --- reading the documents (pure) -------------------------------------------


def ecosystem(purl: str) -> str:
    for prefix, label in ECOSYSTEMS:
        if purl.startswith(f"pkg:{prefix}/"):
            return label
    return OTHER


def license_of(component: dict) -> str:
    """CycloneDX spells a license three ways — `{license: {id}}` for an SPDX id,
    `{license: {name}}` for anything unrecognised, and `{expression}` for a
    compound like `Apache-2.0 OR MIT`. All three are one column here; a reader
    wants to know what the terms are, not which slot the generator used."""
    names: list[str] = []
    for entry in component.get("licenses") or []:
        if "expression" in entry:
            value = entry.get("expression") or ""
        else:
            license_ = entry.get("license") or {}
            value = license_.get("id") or license_.get("name") or ""
        value = " ".join(str(value).split())
        if value and value not in names:
            names.append(value)
    return ", ".join(names)


def collect(documents: Iterable[dict]) -> dict[str, list[Package]]:
    """Every component in every document, grouped by ecosystem and deduped.

    Two documents overlap by design (the image carries the built plugin bundles
    the web lock also names), and one document repeats a component per LOCATION
    — six copies of a vendored `.exe` found at six paths. Identity here is
    (name, version): the same package at two paths is one line in a bill of
    materials.

    Dropped: anything with neither a purl nor a version, which is syft's
    per-file residue rather than a package.
    """
    seen: dict[str, dict[tuple[str, str], Package]] = {}
    for document in documents:
        for component in document.get("components") or []:
            purl = component.get("purl") or ""
            name = (component.get("name") or "").strip()
            version = (component.get("version") or "").strip()
            if not name or (not purl and not version):
                continue
            group = seen.setdefault(ecosystem(purl), {})
            package = Package(name, version, license_of(component))
            existing = group.get((name, version))
            # A duplicate is only worth keeping for what the first copy lacked:
            # syft licenses a package from the metadata it happened to read, so
            # the npm-lock copy can name terms the image copy left blank.
            if existing is None or (not existing.license and package.license):
                group[(name, version)] = package
    return {
        label: sorted(seen[label].values(), key=lambda p: (p.name.lower(), p.version))
        for label in SECTION_ORDER
        if seen.get(label)
    }


def tools(documents: Iterable[dict]) -> list[str]:
    """Who catalogued this, per the documents themselves — CycloneDX 1.5+ nests
    `metadata.tools.components`, earlier versions make `tools` a bare list. Read,
    never hardcoded: the page must not claim syft produced something syft did
    not."""
    found: list[str] = []
    for document in documents:
        raw = (document.get("metadata") or {}).get("tools") or []
        entries = raw.get("components") or [] if isinstance(raw, dict) else raw
        for entry in entries:
            name = (entry.get("name") or "").strip()
            if not name:
                continue
            version = (entry.get("version") or "").strip()
            label = f"{name} {version}" if version else name
            if label not in found:
                found.append(label)
    return found


# --- rendering (pure) --------------------------------------------------------


def _cell(text: str) -> str:
    """A table cell. A pipe inside a cell ends it — GFM wants it escaped even
    inside a code span, which is where names and versions are rendered so that
    `python_dateutil` is not read as emphasis."""
    return " ".join(text.split()).replace("\\", "").replace("|", "\\|").replace("`", "")


def _prose(version: str, groups: dict[str, list[Package]], tool_labels: list[str],
           assets: list[str], tag: str, repo_url: str) -> list[str]:
    total = sum(len(packages) for packages in groups.values())
    catalogued = " and ".join(f"`{label}`" for label in tool_labels) or "the release pipeline"
    release = f"{repo_url}/releases/tag/{tag}" if repo_url else ""
    lines = [
        f"Every dependency **Radd {version}** ships: {total} components, catalogued by "
        f"{catalogued} when the tag was built"
        + (f", rendered from the two CycloneDX documents attached to [the release]({release})."
           if release else " from two CycloneDX documents."),
        "",
        "Two documents, because no single scan sees the whole product: the runtime image "
        "carries the BUILT web bundle, so cataloguing it finds Debian, Python and the Rust "
        "crates read out of binaries — and never the npm tree, which is catalogued "
        "separately from `web/package-lock.json` (production dependencies only).",
        "",
        "| Section | Components |",
        "| --- | ---: |",
    ]
    lines += [f"| {label} | {len(packages)} |" for label, packages in groups.items()]
    lines.append(f"| **Total** | **{total}** |")
    if assets and repo_url:
        lines += [
            "",
            "Raw documents: "
            + " · ".join(
                f"[{name}]({repo_url}/releases/download/{tag}/{name})" for name in assets
            ),
        ]
    return lines


def render(version: str, groups: dict[str, list[Package]], tool_labels: list[str],
           assets: list[str], tag: str, repo_url: str) -> str:
    """The whole page. Markdown only, no inline HTML: Radd's viewer is CommonMark
    (+ GFM tables) and prints raw HTML literally (RADD-942).

    The full listing IS the deliverable — a bill of materials that summarises is
    a summary, and the question it exists to answer ("do we ship X?") is a
    browser find over the complete tables.
    """
    lines = _prose(version, groups, tool_labels, assets, tag, repo_url)
    for label, packages in groups.items():
        lines += [
            "",
            f"## {label} ({len(packages)})",
            "",
            "| Package | Version | License |",
            "| --- | --- | --- |",
        ]
        lines += [
            f"| `{_cell(p.name)}` | `{_cell(p.version)}` | {_cell(p.license)} |"
            for p in packages
        ]
    lines += ["", f"_Generated by `scripts/sbom_page.py` from {', '.join(assets)}._"]
    return "\n".join(lines) + "\n"


# --- publishing --------------------------------------------------------------


def find_page(rows: Iterable[dict], title: str, parent_id: str | None) -> dict | None:
    """Locate a page by (parent, title) in one space listing — the same identity
    `_find_or_create_page` writes by, so the parent this resolves is the page the
    changelog step created."""
    for row in rows:
        if row.get("title") == title and (row.get("parent_id") or None) == parent_id:
            return row
    return None


def find_space(base: str, token: str) -> dict | None:
    """Never find-or-CREATE: a missing space means the release notes were never
    published, and the version page this needs is missing with it. Creating the
    structure here would build an empty shell around a failure."""
    for space in _request(f"{base}/api/v1/page-spaces", token):  # type: ignore[union-attr]
        if space.get("slug") == SPACE_SLUG or space.get("name") == SPACE_NAME:
            return space
    return None


def publish(base: str, token: str, version: str, markdown: str) -> str:
    space = find_space(base, token)
    if space is None:
        raise MissingParent(
            f"no '{SPACE_NAME}' space on {base} — release_notes.py has never published here"
        )
    rows = _request(f"{base}/api/v1/page-spaces/{space['id']}/pages", token)
    root = find_page(rows, ROOT_PAGE, None)  # type: ignore[arg-type]
    section = find_page(rows, SECTION_PAGE, root["id"]) if root else None  # type: ignore[arg-type]
    parent = find_page(rows, version, section["id"]) if section else None  # type: ignore[arg-type]
    if parent is None:
        raise MissingParent(
            f"no '{version}' page under {SPACE_NAME} → {ROOT_PAGE} → {SECTION_PAGE} on {base}"
            " — the changelog step publishes it and the SBOM hangs off it;"
            " filing it anywhere else would hide it"
        )
    page = _find_or_create_page(base, token, space, f"{TITLE_PREFIX}{version}", parent["id"], markdown)
    return f"{base}/pages/{space['slug']}/{page['slug']}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True, help="the version tag, e.g. v0.32.0")
    parser.add_argument("--dry-run", action="store_true", help="print the body, publish nothing")
    parser.add_argument("documents", nargs="+", help="CycloneDX JSON documents")
    args = parser.parse_args(argv)

    tag = args.tag if args.tag.startswith("v") else f"v{args.tag}"
    version = tag[1:]
    radd_base = os.environ.get("RADD_BASE_URL", "https://project.radd-hq.com").rstrip("/")
    repo_url = release_host.from_env().repo_url

    documents = []
    for path in args.documents:
        try:
            with open(path, encoding="utf-8") as handle:
                documents.append(json.load(handle))
        except (OSError, ValueError) as exc:
            print(f"! cannot read {path}: {exc}", file=sys.stderr)
            return 1

    groups = collect(documents)
    if not groups:
        print(
            f"! {', '.join(args.documents)} list no components — refusing to publish an"
            " empty bill of materials",
            file=sys.stderr,
        )
        return 1

    markdown = render(
        version,
        groups,
        tools(documents),
        [os.path.basename(path) for path in args.documents],
        tag,
        repo_url,
    )
    if args.dry_run:
        print(markdown)
        return 0

    token = os.environ.get("RADD_API_TOKEN", "")
    if not token:
        print("! RADD_API_TOKEN unset — cannot publish the SBOM page", file=sys.stderr)
        return 1
    try:
        print(f"page:    {publish(radd_base, token, version, markdown)}")
    except MissingParent as exc:
        print(f"! {exc}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, OSError, KeyError) as exc:  # noqa: BLE001
        print(f"! publishing the SBOM page for {version} failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
