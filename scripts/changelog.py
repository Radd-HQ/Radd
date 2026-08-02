#!/usr/bin/env python3
"""The changelog for a version, categorized by what actually changed (RADD-704).

ONE generator feeds two consumers — the Forgejo release body and the Pages
release-notes entry (RADD-703) — because two implementations of "what shipped in
0.6.0" would disagree the first week.

It lives here, in a committed script CI invokes, rather than as a shell pipeline
inside publish.yaml: the categorization is real logic that has to be readable and
testable, and YAML is where logic goes to rot.

**A commit's category comes from its ISSUE, not from its subject line.** Every
commit carries exactly one `[RADD-###]` (the working agreement), so the tracker
already knows whether the work was a bug or a feature — parsing an English
prefix off the subject would be inventing a second, worse source of truth.

    Bug                              -> Bugfix
    Feature/Story + a UI label       -> New UI Feature
    Feature/Story                    -> New Feature
    Task/Chore                       -> Chore
    any type + a docs label          -> Documentation
    unreachable / unfiled            -> Uncategorized

A tag must publish even when the tracker is down or a key was never filed, so
every lookup failure degrades to Uncategorized carrying the raw subject rather
than aborting the release.

Usage:
    changelog.py --from v0.5.0 --to v0.6.0 [--format markdown|json]
                 [--base-url https://project.radd-hq.com] [--token <PAT>]

`--from` defaults to the previous tag, `--to` to the current one.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field

KEY_RE = re.compile(r"\[(RADD-\d+)\]")
DEFAULT_BASE_URL = "https://project.radd-hq.com"

#: Labels that mark a feature as user-facing UI rather than plumbing.
UI_LABELS = frozenset({"web", "board", "views", "ui", "frontend"})

#: Labels meaning "this change IS documentation". Deliberately NOT `docs`:
#: in this tracker `docs` is a MODULE label (the pages subsystem), so the first
#: real run put the entire Pages rename under Documentation — module labels name
#: the area a change touches, never the nature of the change.
DOC_LABELS = frozenset({"documentation"})

#: Rendering order — what a reader most wants first.
CATEGORIES = [
    "Bugfix",
    "New Feature",
    "New UI Feature",
    "Chore",
    "Documentation",
    "Uncategorized",
]


@dataclass
class Entry:
    key: str | None
    subject: str
    sha: str
    title: str = ""
    category: str = "Uncategorized"


@dataclass
class Changelog:
    version: str
    previous: str
    entries: list[Entry] = field(default_factory=list)

    def by_category(self) -> dict[str, list[Entry]]:
        grouped: dict[str, list[Entry]] = {}
        for entry in self.entries:
            grouped.setdefault(entry.category, []).append(entry)
        return {name: grouped[name] for name in CATEGORIES if name in grouped}


def categorize(issue_type: str, labels: list[str]) -> str:
    """The mapping above, as one function so both consumers agree."""
    lowered = {label.lower() for label in labels}
    if lowered & DOC_LABELS:
        return "Documentation"
    kind = (issue_type or "").strip().lower()
    if kind == "bug":
        return "Bugfix"
    if kind in {"feature", "story"}:
        return "New UI Feature" if lowered & UI_LABELS else "New Feature"
    if kind in {"task", "chore"}:
        return "Chore"
    return "Uncategorized"


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def previous_tag(tag: str) -> str:
    """The tag before `tag`, or the repo's first commit when there is none."""
    try:
        return git("describe", "--tags", "--abbrev=0", f"{tag}^")
    except subprocess.CalledProcessError:
        return git("rev-list", "--max-parents=0", "HEAD")


def commits(previous: str, tag: str) -> list[Entry]:
    raw = git("log", "--no-merges", "--format=%H%x1f%s", f"{previous}..{tag}")
    entries: list[Entry] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        sha, _, subject = line.partition("\x1f")
        match = KEY_RE.search(subject)
        entries.append(
            Entry(key=match.group(1) if match else None, subject=subject, sha=sha[:8])
        )
    return entries


def fetch_issue(base_url: str, token: str, key: str) -> dict | None:
    """The item behind a key. Returns None on ANY failure — a release must not
    depend on the tracker being reachable."""
    request = urllib.request.Request(f"{base_url}/api/v1/items/by-key/{key}")
    request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read())
    except (urllib.error.URLError, OSError, ValueError) as exc:  # noqa: BLE001
        print(f"  ! {key}: {exc}", file=sys.stderr)
        return None


def enrich(entries: list[Entry], base_url: str, token: str) -> None:
    """Fill title + category from the tracker, in place. Cached per key so a
    version that touched one issue in three commits asks once."""
    seen: dict[str, dict | None] = {}
    for entry in entries:
        if not entry.key:
            continue
        if entry.key not in seen:
            seen[entry.key] = fetch_issue(base_url, token, entry.key) if token else None
        item = seen[entry.key]
        if not item:
            continue
        entry.title = item.get("title", "")
        entry.category = categorize(
            (item.get("type") or {}).get("name", ""), item.get("labels") or []
        )


def render_markdown(log: Changelog, base_url: str) -> str:
    lines = [f"## {log.version}", ""]
    grouped = log.by_category()
    if not grouped:
        lines.append("_No commits in this range._")
        return "\n".join(lines)
    for category, entries in grouped.items():
        lines.append(f"### {category}")
        lines.append("")
        for entry in entries:
            text = entry.title or entry.subject
            if entry.key:
                lines.append(f"- [{entry.key}]({base_url}/issues/{entry.key}) {text}")
            else:
                lines.append(f"- {text} (`{entry.sha}`)")
        lines.append("")
    lines.append(f"_Changes from {log.previous} to {log.version}._")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--to", default=None, help="tag to describe (default: current HEAD tag)")
    parser.add_argument("--from", dest="from_", default=None, help="previous tag")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--base-url", default=os.environ.get("RADD_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--token", default=os.environ.get("RADD_API_TOKEN", ""))
    args = parser.parse_args()

    tag = args.to or git("describe", "--tags", "--abbrev=0")
    previous = args.from_ or previous_tag(tag)
    log = Changelog(version=tag, previous=previous, entries=commits(previous, tag))
    enrich(log.entries, args.base_url.rstrip("/"), args.token)

    if args.format == "json":
        print(
            json.dumps(
                {
                    "version": log.version,
                    "previous": log.previous,
                    "categories": {
                        name: [
                            {"key": e.key, "title": e.title or e.subject, "sha": e.sha}
                            for e in entries
                        ]
                        for name, entries in log.by_category().items()
                    },
                },
                indent=2,
            )
        )
    else:
        print(render_markdown(log, args.base_url.rstrip("/")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
