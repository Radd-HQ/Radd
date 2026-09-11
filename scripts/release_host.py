"""Where a version's release lives: GitHub or Forgejo, chosen by environment.

One tiny seam shared by release_notes.py, release_assets.py and sbom_page.py so
the three scripts agree on which host owns the release, how to authenticate,
and what a release or asset URL looks like — instead of each carrying its own
copy of the Forgejo calls and drifting (RADD-1128).

Selection (first match wins):
    RELEASE_TARGET=github|forgejo     explicit
    GITHUB_ACTIONS=true               inside a GitHub workflow -> github
    otherwise                         forgejo (self-hosters on Forgejo/Gitea)

GitHub environment (all set by GitHub Actions; override for local runs):
    GITHUB_REPOSITORY   owner/repo            GITHUB_TOKEN    repo write
    GITHUB_API_URL      https://api.github.com GITHUB_SERVER_URL https://github.com

Forgejo environment:
    FORGEJO_BASE_URL    default https://git.radd-hq.com
    FORGEJO_REPO        default Radd/Radd
    FORGEJO_TOKEN       token with repo write (releases)
"""

from __future__ import annotations

import json
import mimetypes
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class ReleaseHost:
    kind: str          # "github" | "forgejo"
    api: str           # API base, no trailing slash
    web: str           # web base, no trailing slash
    repo: str          # owner/name
    token: str

    # --- URLs ---------------------------------------------------------------

    @property
    def repo_url(self) -> str:
        return f"{self.web}/{self.repo}"

    def release_url(self, tag: str) -> str:
        return f"{self.repo_url}/releases/tag/{tag}"

    def download_url(self, tag: str, name: str) -> str:
        return f"{self.repo_url}/releases/download/{tag}/{name}"

    @property
    def _releases(self) -> str:
        prefix = "/repos" if self.kind == "github" else "/api/v1/repos"
        return f"{self.api}{prefix}/{self.repo}/releases"

    # --- HTTP ---------------------------------------------------------------

    def request(
        self,
        url: str,
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
        request.add_header("Authorization", f"Bearer {self.token}")
        request.add_header("Content-Type", content_type or "application/json")
        if self.kind == "github":
            request.add_header("Accept", "application/vnd.github+json")
            request.add_header("X-GitHub-Api-Version", "2022-11-28")
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}

    # --- releases -----------------------------------------------------------

    def get_release(self, tag: str) -> dict | None:
        try:
            return self.request(f"{self._releases}/tags/{tag}")  # type: ignore[return-value]
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise

    def find_or_create_release(self, tag: str, name: str, body: str | None = None) -> dict:
        """Create the release, or return the existing one; when `body` is given
        an existing release has its notes replaced (a re-run must not 409)."""
        existing = self.get_release(tag)
        if existing is not None:
            if body is not None:
                existing = self.request(  # type: ignore[assignment]
                    f"{self._releases}/{existing['id']}", "PATCH", {"body": body}
                )
            return existing  # type: ignore[return-value]
        payload: dict = {"tag_name": tag, "name": name}
        if body is not None:
            payload["body"] = body
        try:
            return self.request(self._releases, "POST", payload)  # type: ignore[return-value]
        except urllib.error.HTTPError as exc:
            if exc.code not in (409, 422):
                raise
            # Lost a creation race with the other publish step: it exists now.
            found = self.get_release(tag)
            if found is None:
                raise
            return found

    def release_html_url(self, release: dict, tag: str) -> str:
        return release.get("html_url") or self.release_url(tag)

    # --- assets -------------------------------------------------------------

    def attach(self, release: dict, path: str) -> str:
        """Upload `path` as a release asset, replacing a same-named one."""
        name = os.path.basename(path)
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        with open(path, "rb") as fh:
            payload = fh.read()
        if self.kind == "github":
            for asset in release.get("assets") or []:
                if asset["name"] == name:
                    self.request(f"{self.api}/repos/{self.repo}/releases/assets/{asset['id']}", "DELETE")
            upload = release.get("upload_url", "").split("{", 1)[0]
            if not upload:
                upload = f"https://uploads.github.com/repos/{self.repo}/releases/{release['id']}/assets"
            uploaded = self.request(
                f"{upload}?name={urllib.parse.quote(name)}", "POST", data=payload, content_type=mime
            )
            return uploaded.get("browser_download_url", name)  # type: ignore[union-attr]
        assets_url = f"{self._releases}/{release['id']}/assets"
        for asset in release.get("assets") or []:
            if asset["name"] == name:
                self.request(f"{assets_url}/{asset['id']}", "DELETE")
        boundary = os.urandom(16).hex()
        form = (
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="attachment"; filename="{name}"\r\n'
                f"Content-Type: {mime}\r\n\r\n"
            ).encode()
            + payload
            + f"\r\n--{boundary}--\r\n".encode()
        )
        uploaded = self.request(
            f"{assets_url}?name={urllib.parse.quote(name)}",
            "POST",
            data=form,
            content_type=f"multipart/form-data; boundary={boundary}",
        )
        return uploaded.get("browser_download_url", name)  # type: ignore[union-attr]


def from_env(environ: dict[str, str] | None = None) -> ReleaseHost:
    env = os.environ if environ is None else environ
    target = env.get("RELEASE_TARGET") or ("github" if env.get("GITHUB_ACTIONS") == "true" else "forgejo")
    if target == "github":
        return ReleaseHost(
            kind="github",
            api=env.get("GITHUB_API_URL", "https://api.github.com").rstrip("/"),
            web=env.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/"),
            repo=env.get("GITHUB_REPOSITORY", "radd-hq/radd"),
            token=env.get("GITHUB_TOKEN", ""),
        )
    base = env.get("FORGEJO_BASE_URL", "https://git.radd-hq.com").rstrip("/")
    return ReleaseHost(
        kind="forgejo",
        api=base,
        web=base,
        repo=env.get("FORGEJO_REPO", "Radd/Radd"),
        token=env.get("FORGEJO_TOKEN", ""),
    )
