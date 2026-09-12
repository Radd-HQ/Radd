#!/usr/bin/env python3
"""Mirror the "Radd Documentation" page tree onto the GitHub wiki (RADD-1137).

project.radd-hq.com answers 401 to anonymous visitors, so the user guide, the
developer guide and the release notes that live there as one page tree are
invisible to anyone who has not been given an account. A GitHub wiki is a git
repository of Markdown, so this publishes a COPY there — prod stays where the
docs are written, the wiki never diverges (editing is restricted to
collaborators on GitHub, and every run rebuilds the whole tree).

What the RADD-721 export gives and what this has to add:

- The export is a zip of `.md` files with links between exported pages already
  rewritten to relative paths. Kept, then translated to wiki page names.
- Image links stay `(/api/v1/attachments/<id>)` — instance-relative, behind a
  login. Left alone, every screenshot in the user guide is a broken image on
  GitHub. So each attachment is DOWNLOADED and committed into the wiki repo
  under `images/`, with the reference rewritten. The export itself stays
  instance-relative on purpose: a re-import must round-trip the ids.
- GitHub wikis are a FLAT namespace: one `<Title>.md` per page, the URL is the
  title with spaces as hyphens, and the hierarchy is whatever `_Sidebar.md`
  says. Titles come from each page's first heading; a duplicate title is a
  hard error, because two pages would silently become one.

Runs from the maintainer's machine with the owner key (no service account, no
CI secret — Hussein's call). The wiki repo must already exist: GitHub creates
`<repo>.wiki.git` when the first page is saved in the UI, and a push to a wiki
that was never initialised is refused.

Usage:
    python3 scripts/publish_wiki.py --wiki /path/to/radd.wiki [--push] [--dry-run]

Environment: RADD_API_TOKEN (falls back to ~/.radd-token), RADD_BASE_URL
(default https://project.radd-hq.com).
"""

from __future__ import annotations

import argparse
import io
import mimetypes
import os
import posixpath
import re
import subprocess
import sys
import urllib.request
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_BASE = "https://project.radd-hq.com"
#: The "Radd Documentation" page on project.radd-hq.com — the tree's root.
DEFAULT_ROOT_PAGE = "70d3f5c9-5e52-4b14-b97d-27997ca1e82f"
IMAGES_DIR = "images"

_ATTACHMENT = re.compile(r"\]\((?:https?://[^/\s)]+)?/api/v1/attachments/(?P<id>[0-9a-f-]{36})[^)]*\)")
_REL_LINK = re.compile(r"\]\((?P<path>(?![a-z]+:|/|#)[^)#\s]+\.md)(?P<anchor>#[^)\s]*)?\)")
_HEADING = re.compile(r"^#\s+(?P<title>.+?)\s*$", re.MULTILINE)
_VERSION = re.compile(r"^\d+(\.\d+)*$")
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass
class Page:
    archive_path: str  # e.g. radd-documentation/user-guide/views.md
    body: str
    title: str = ""
    wiki_name: str = ""  # file stem: "User-guide"
    children: list[Page] = field(default_factory=list)
    is_index: bool = False

    @property
    def dir(self) -> str:
        return posixpath.dirname(self.archive_path)

    @property
    def link(self) -> str:
        return self.wiki_name


# --- fetching -------------------------------------------------------------------


def _token() -> str:
    env = os.environ.get("RADD_API_TOKEN", "").strip()
    if env:
        return env
    path = Path("~/.radd-token").expanduser()
    if path.exists():
        return path.read_text().strip()
    sys.exit("no RADD_API_TOKEN and no ~/.radd-token")


def _get(base: str, token: str, path: str) -> tuple[bytes, str]:
    req = urllib.request.Request(base + path, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read(), resp.headers.get("content-type", "")


# --- the tree -------------------------------------------------------------------


def load_pages(blob: bytes) -> list[Page]:
    pages: list[Page] = []
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        for name in sorted(zf.namelist()):
            if not name.endswith(".md"):
                continue
            body = zf.read(name).decode("utf-8")
            pages.append(Page(archive_path=name, body=body, is_index=posixpath.basename(name) == "index.md"))
    return pages


def title_of(page: Page) -> str:
    m = _HEADING.search(page.body)
    if m:
        return m.group("title").strip()
    stem = posixpath.basename(page.dir if page.is_index else page.archive_path[:-3])
    return stem.replace("-", " ").strip().capitalize()


def wiki_name_of(title: str) -> str:
    # GitHub turns "-" back into a space for display and uses the hyphenated
    # form in URLs; anything it cannot put in a filename is dropped.
    cleaned = _UNSAFE.sub("", title).strip()
    return re.sub(r"\s+", "-", cleaned)


def build_tree(pages: list[Page]) -> Page:
    by_dir: dict[str, Page] = {}
    for p in pages:
        p.title = title_of(p)
        p.wiki_name = wiki_name_of(p.title)
        if p.is_index:
            by_dir[p.dir] = p
    roots = [p for p in pages if p.is_index and posixpath.dirname(p.dir) == ""]
    if len(roots) != 1:
        sys.exit(f"expected exactly one top-level index.md, found {[r.archive_path for r in roots]}")
    root = roots[0]
    for p in pages:
        if p is root:
            continue
        parent_dir = posixpath.dirname(p.dir) if p.is_index else p.dir
        parent = by_dir.get(parent_dir)
        if parent is None:
            sys.exit(f"{p.archive_path}: no index.md for its parent directory {parent_dir!r}")
        parent.children.append(p)
    for p in pages:
        p.children.sort(key=_child_sort_key)
    return root


def _child_sort_key(p: Page):
    # Release notes newest first; everything else alphabetical by title.
    if _VERSION.match(p.title):
        return (0, tuple(-int(x) for x in p.title.split(".")))
    return (1, p.title.lower())


def check_unique(pages: list[Page]) -> None:
    seen: dict[str, str] = {}
    for p in pages:
        key = p.wiki_name.lower()
        if key in seen:
            sys.exit(f"duplicate wiki page name {p.wiki_name!r}: {seen[key]} and {p.archive_path}")
        seen[key] = p.archive_path


# --- rewriting ------------------------------------------------------------------


def rewrite_links(page: Page, by_path: dict[str, Page]) -> str:
    def repl(m: re.Match) -> str:
        target = posixpath.normpath(posixpath.join(page.dir, m.group("path")))
        dest = by_path.get(target)
        if dest is None:
            print(f"  warn: {page.archive_path}: link to {m.group('path')} not in export; left as is")
            return m.group(0)
        return f"]({dest.link}{m.group('anchor') or ''})"

    return _REL_LINK.sub(repl, page.body)


def fetch_images(
    pages: list[Page], base: str, token: str, wiki: Path, dry_run: bool
) -> dict[str, str]:
    """Download every attachment referenced by any page into wiki/images/.

    Returns {attachment id: relative path}. The extension comes from the
    content-type — the export carries no filename, and GitHub renders an
    extension-less image as a download link.
    """
    ids: dict[str, None] = {}
    for p in pages:
        for m in _ATTACHMENT.finditer(p.body):
            ids.setdefault(m.group("id"), None)
    out: dict[str, str] = {}
    images = wiki / IMAGES_DIR
    images.mkdir(exist_ok=True)
    existing = {f.stem: f.name for f in images.iterdir() if f.is_file()}
    for i, att_id in enumerate(ids, 1):
        if att_id in existing:
            out[att_id] = f"{IMAGES_DIR}/{existing[att_id]}"
            continue
        if dry_run:
            out[att_id] = f"{IMAGES_DIR}/{att_id}.bin"
            continue
        data, ctype = _get(base, token, f"/api/v1/attachments/{att_id}")
        ext = mimetypes.guess_extension(ctype.split(";")[0].strip()) or ".bin"
        if ext == ".jpe":
            ext = ".jpg"
        (images / f"{att_id}{ext}").write_bytes(data)
        out[att_id] = f"{IMAGES_DIR}/{att_id}{ext}"
        print(f"  image {i}/{len(ids)}: {att_id}{ext} ({len(data) // 1024} KB)")
    return out


def rewrite_images(body: str, images: dict[str, str]) -> str:
    return _ATTACHMENT.sub(lambda m: f"]({images[m.group('id')]})", body)


# --- output ---------------------------------------------------------------------


def sidebar(root: Page) -> str:
    lines = [f"**[{root.title}](Home)**", ""]

    def walk(p: Page, depth: int) -> None:
        for c in p.children:
            lines.append(f"{'  ' * depth}- [{c.title}]({c.link})")
            # Release-note versions: keep the sidebar to the versions themselves;
            # each version page links its own SBOM.
            if not _VERSION.match(c.title):
                walk(c, depth + 1)

    walk(root, 0)
    return "\n".join(lines) + "\n"


def footer(base: str, exported_at: datetime) -> str:
    return (
        "\n\n---\n"
        f"*Mirrored from [{base.removeprefix('https://')}]({base}) on "
        f"{exported_at:%Y-%m-%d}. Documentation is written there; this copy is "
        "regenerated by `scripts/publish_wiki.py` and hand edits do not survive it.*\n"
    )


def children_list(p: Page) -> str:
    if not p.children:
        return ""
    return "\n\n## Pages\n\n" + "\n".join(f"- [{c.title}]({c.link})" for c in p.children) + "\n"


def write_wiki(root: Page, pages: list[Page], images: dict[str, str], wiki: Path, base: str) -> None:
    by_path = {p.archive_path: p for p in pages}
    now = datetime.now(UTC)
    keep = {"_Sidebar.md", "Home.md"} | {f"{p.wiki_name}.md" for p in pages if p is not root}
    for old in wiki.glob("*.md"):
        if old.name not in keep:
            old.unlink()
            print(f"  removed {old.name} (no longer in the tree)")
    for p in pages:
        body = rewrite_images(rewrite_links(p, by_path), images)
        if p.is_index:
            body = body.rstrip() + children_list(p)
        body = body.rstrip() + footer(base, now)
        name = "Home.md" if p is root else f"{p.wiki_name}.md"
        (wiki / name).write_text(body)
    (wiki / "_Sidebar.md").write_text(sidebar(root))
    # The Home page's own link target is "Home", not the root title.
    home = (wiki / "Home.md").read_text().replace(f"]({root.link})", "](Home)")
    (wiki / "Home.md").write_text(home)


def git(wiki: Path, *args: str, check: bool = True) -> str:
    res = subprocess.run(["git", "-C", str(wiki), *args], capture_output=True, text=True)
    if check and res.returncode:
        sys.exit(f"git {' '.join(args)} failed:\n{res.stderr}")
    return res.stdout


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wiki", required=True, help="local clone of <repo>.wiki.git")
    ap.add_argument("--base", default=os.environ.get("RADD_BASE_URL", DEFAULT_BASE))
    ap.add_argument("--root", default=DEFAULT_ROOT_PAGE, help="page id of the tree's root")
    ap.add_argument("--push", action="store_true", help="commit and push when something changed")
    ap.add_argument("--dry-run", action="store_true", help="no downloads, no git")
    args = ap.parse_args()

    wiki = Path(args.wiki).expanduser().resolve()
    if not (wiki / ".git").exists() and not args.dry_run:
        sys.exit(f"{wiki} is not a git checkout — clone the wiki repo there first")
    wiki.mkdir(parents=True, exist_ok=True)

    token = _token()
    print(f"exporting {args.root} from {args.base}")
    blob, _ = _get(args.base, token, f"/api/v1/pages/{args.root}/export")
    pages = load_pages(blob)
    root = build_tree(pages)
    check_unique(pages)
    print(f"  {len(pages)} pages, root {root.title!r}")

    images = fetch_images(pages, args.base, token, wiki, args.dry_run)
    print(f"  {len(images)} images")
    write_wiki(root, pages, images, wiki, args.base)

    if args.dry_run:
        print("dry run: files written, no git")
        return 0
    git(wiki, "add", "-A")
    if not git(wiki, "status", "--porcelain").strip():
        print("no changes — wiki already matches prod")
        return 0
    summary = git(wiki, "diff", "--cached", "--stat").strip().splitlines()[-1]
    git(wiki, "commit", "-q", "-m", f"Mirror Radd Documentation from {args.base} ({datetime.now(UTC):%Y-%m-%d %H:%M} UTC)\n\n{summary}")
    print(f"committed: {summary}")
    if args.push:
        git(wiki, "push", "-q")
        print("pushed")
    else:
        print("not pushed (pass --push)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
