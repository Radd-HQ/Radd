#!/usr/bin/env python3
"""Publish a version's changelog: a release on the git host, and a page in Pages.

Both bodies come from `changelog.py` — one generator, two destinations, so the
release notes on git.radd-hq.com and the ones in the wiki can never disagree
(RADD-703 / RADD-704).

The page structure is created on demand and is IDEMPOTENT at every level, so
re-running a version updates its page instead of growing a second one:

    Space:  Radd
      Page: Radd Documentation
        Page: Release notes
          Page: 0.6.0     <- the changelog

Usage:
    release_notes.py --tag v0.6.0 [--from v0.5.0]
                     [--skip-release] [--skip-page] [--dry-run]

Environment:
    RADD_BASE_URL        default https://project.radd-hq.com
    RADD_API_TOKEN       PAT with page.write (+ item.read for the changelog)
    The git host (GitHub inside GitHub Actions, Forgejo otherwise) and its
    token come from release_host.py: RELEASE_TARGET, GITHUB_REPOSITORY,
    GITHUB_TOKEN / FORGEJO_BASE_URL, FORGEJO_REPO, FORGEJO_TOKEN.

Failing to publish is reported and returns non-zero, but the two destinations
are independent: a wiki that is down must not stop the git release, and vice
versa.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import release_host  # noqa: E402
from changelog import (  # noqa: E402
    Changelog,
    commits,
    enrich,
    git,
    previous_tag,
    render_markdown,
)

SPACE_NAME = "Radd"
SPACE_SLUG = "radd"
ROOT_PAGE = "Radd Documentation"
SECTION_PAGE = "Release notes"


def _request(url: str, token: str, method: str = "GET", body: dict | None = None) -> dict | list:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
    )
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
        return json.loads(raw) if raw else {}


# --- Pages (RADD-703) -------------------------------------------------------


def _find_or_create_space(base: str, token: str) -> dict:
    spaces = _request(f"{base}/api/v1/page-spaces", token)
    for space in spaces:  # type: ignore[union-attr]
        if space["slug"] == SPACE_SLUG or space["name"] == SPACE_NAME:
            return space
    return _request(  # type: ignore[return-value]
        f"{base}/api/v1/page-spaces",
        token,
        "POST",
        {
            "name": SPACE_NAME,
            "slug": SPACE_SLUG,
            "description": "How Radd works, and what changed in each release.",
        },
    )


def _find_or_create_page(
    base: str, token: str, space: dict, title: str, parent_id: str | None, body: str,
    overwrite: bool = True,
) -> dict:
    """Find by (parent, title) and update, else create. Title is the identity
    here rather than the slug: a page whose URL someone deliberately changed is
    still the same page, and re-running a release must not fork it.

    `overwrite=False` (RADD-862): the body applies at CREATION only — for the
    structural root/section pages, whose content belongs to the operator once
    they exist. The 0.20.0 publish silently reset the section to its default,
    deleting the radd:children embed fence placed there minutes earlier."""
    rows = _request(f"{base}/api/v1/page-spaces/{space['id']}/pages", token)
    for row in rows:  # type: ignore[union-attr]
        if row["title"] == title and (row["parent_id"] or None) == parent_id:
            current = _request(f"{base}/api/v1/pages/{row['id']}", token)
            if overwrite and body and current.get("body") != body:  # type: ignore[union-attr]
                return _request(  # type: ignore[return-value]
                    f"{base}/api/v1/pages/{row['id']}", token, "PATCH", {"body": body}
                )
            return current  # type: ignore[return-value]
    payload = {"space_id": space["id"], "title": title, "body": body}
    if parent_id:
        payload["parent_id"] = parent_id
    return _request(f"{base}/api/v1/pages", token, "POST", payload)  # type: ignore[return-value]


def publish_page(base: str, token: str, version: str, markdown: str) -> str:
    space = _find_or_create_space(base, token)
    root = _find_or_create_page(
        base,
        token,
        space,
        ROOT_PAGE,
        None,
        "Radd's own documentation. Release notes are generated per version by "
        "`scripts/release_notes.py` when a tag is pushed.",
        overwrite=False,
    )
    section = _find_or_create_page(
        base,
        token,
        space,
        SECTION_PAGE,
        root["id"],
        # The creation default IS the unified page (RADD-858): every child
        # transcluded, live. Never overwritten after creation.
        "One page per released version.\n\n"
        "```radd:children\n{\"mode\": \"embed\"}\n```\n",
        overwrite=False,
    )
    page = _find_or_create_page(base, token, space, version, section["id"], markdown)
    return f"{base}/pages/{space['slug']}/{page['slug']}"


# --- the git host's release (RADD-704, host-agnostic since RADD-1128) --------


def publish_release(host: release_host.ReleaseHost, tag: str, markdown: str) -> str:
    """Create the release, or update its notes when the tag was already
    released (a re-run of the workflow must not 409 the whole job)."""
    release = host.find_or_create_release(tag, f"Radd {tag.lstrip('v')}", body=markdown)
    return host.release_html_url(release, tag)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default=None)
    parser.add_argument("--from", dest="from_", default=None)
    parser.add_argument("--skip-release", "--skip-forgejo", dest="skip_release", action="store_true")
    parser.add_argument("--skip-page", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="print the body, publish nothing")
    args = parser.parse_args()

    radd_base = os.environ.get("RADD_BASE_URL", "https://project.radd-hq.com").rstrip("/")
    radd_token = os.environ.get("RADD_API_TOKEN", "")
    host = release_host.from_env()

    tag = args.tag or git("describe", "--tags", "--abbrev=0")
    previous = args.from_ or previous_tag(tag)
    log = Changelog(version=tag, previous=previous, entries=commits(previous, tag))
    enrich(log.entries, radd_base, radd_token)
    markdown = render_markdown(log, radd_base, host.repo_url)

    if args.dry_run:
        print(markdown)
        return 0

    failures = 0
    if not args.skip_release:
        if not host.token:
            print(f"! no {host.kind} token — skipping the git release", file=sys.stderr)
            failures += 1
        else:
            try:
                print(f"release: {publish_release(host, tag, markdown)}")
            except (urllib.error.URLError, OSError, KeyError) as exc:  # noqa: BLE001
                print(f"! {host.kind} release failed: {exc}", file=sys.stderr)
                failures += 1

    if not args.skip_page:
        if not radd_token:
            print("! RADD_API_TOKEN unset — skipping the release-notes page", file=sys.stderr)
            failures += 1
        else:
            try:
                print(f"page:    {publish_page(radd_base, radd_token, tag.lstrip('v'), markdown)}")
            except (urllib.error.URLError, OSError, KeyError) as exc:  # noqa: BLE001
                print(f"! release-notes page failed: {exc}", file=sys.stderr)
                failures += 1

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
