#!/usr/bin/env python3
"""Attach files to a version's Forgejo release (RADD-1026).

publish.yaml uses this to hang the per-release CycloneDX SBOMs off the release
its tag produced. The release normally exists already — the changelog step
creates it — but that step is continue-on-error and this one must work when it
did not, so the release is found-or-created by tag; a bare release created here
gets its body the next time the changelog publishes (release_notes.py PATCHes
an existing release rather than 409ing). Uploading a name that already exists
REPLACES the asset (delete, then upload), so the workflow_dispatch rebuild of a
version refreshes its SBOMs instead of failing or growing twins.

Usage:
    release_assets.py --tag v0.31.1 sbom-image.cdx.json [sbom-web.cdx.json ...]

Environment:
    FORGEJO_BASE_URL     default https://git.radd-hq.com
    FORGEJO_REPO         default Radd/Radd
    FORGEJO_TOKEN        token with repo write (releases)
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid


def _request(
    url: str,
    token: str,
    method: str = "GET",
    body: dict | None = None,
    data: bytes | None = None,
    content_type: str | None = None,
) -> dict | list:
    request = urllib.request.Request(
        url,
        data=data if data is not None else (json.dumps(body).encode() if body is not None else None),
        method=method,
    )
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Content-Type", content_type or "application/json")
    with urllib.request.urlopen(request, timeout=60) as response:
        raw = response.read()
        return json.loads(raw) if raw else {}


def _find_or_create_release(base: str, repo: str, token: str, tag: str) -> dict:
    url = f"{base}/api/v1/repos/{repo}/releases"
    try:
        return _request(f"{url}/tags/{tag}", token)  # type: ignore[return-value]
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
    try:
        return _request(  # type: ignore[return-value]
            url, token, "POST", {"tag_name": tag, "name": f"Radd {tag.lstrip('v')}"}
        )
    except urllib.error.HTTPError as exc:
        if exc.code not in (409, 422):
            raise
        # Lost a creation race (the changelog step finished first): it exists now.
        return _request(f"{url}/tags/{tag}", token)  # type: ignore[return-value]


def _attach(base: str, repo: str, token: str, release: dict, path: str) -> str:
    name = os.path.basename(path)
    assets_url = f"{base}/api/v1/repos/{repo}/releases/{release['id']}/assets"
    for asset in release.get("assets") or []:
        if asset["name"] == name:
            _request(f"{assets_url}/{asset['id']}", token, "DELETE")
    with open(path, "rb") as fh:
        payload = fh.read()
    boundary = uuid.uuid4().hex
    mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
    form = (
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="attachment"; filename="{name}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        ).encode()
        + payload
        + f"\r\n--{boundary}--\r\n".encode()
    )
    uploaded = _request(
        f"{assets_url}?name={urllib.parse.quote(name)}",
        token,
        "POST",
        data=form,
        content_type=f"multipart/form-data; boundary={boundary}",
    )
    return uploaded.get("browser_download_url", name)  # type: ignore[union-attr]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("files", nargs="+")
    args = parser.parse_args()

    base = os.environ.get("FORGEJO_BASE_URL", "https://git.radd-hq.com").rstrip("/")
    repo = os.environ.get("FORGEJO_REPO", "Radd/Radd")
    token = os.environ.get("FORGEJO_TOKEN", "")
    if not token:
        print("! FORGEJO_TOKEN unset — cannot attach release assets", file=sys.stderr)
        return 1
    missing = [f for f in args.files if not os.path.isfile(f)]
    if missing:
        print(f"! not a file: {', '.join(missing)}", file=sys.stderr)
        return 1

    try:
        release = _find_or_create_release(base, repo, token, args.tag)
        for path in args.files:
            print(f"asset: {_attach(base, repo, token, release, path)}")
    except (urllib.error.URLError, OSError, KeyError) as exc:
        print(f"! attaching assets to {args.tag} failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
