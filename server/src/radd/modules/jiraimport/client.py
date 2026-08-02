"""A Jira Server/DC REST v2 client (specs 90, 100).

Spec 100 turned this from a set of module functions reading `settings` into a
`JiraClient` bound to one `JiraCreds`. Two reasons:

- **Connections live in the database now**, so "which Jira" is a per-call fact,
  not deploy configuration.
- **One HTTP connection per client, reused.** The old code built a fresh
  `httpx.Client` per call, which meant a full TCP + TLS handshake for every page
  of a several-hundred-page download. A snapshot download opens one client and
  keeps it.

Calls are synchronous and belong in `asyncio.to_thread` — which is exactly why
they take a plain `JiraCreds` and never a SQLAlchemy row. Connection problems
raise `JiraUnavailable`, distinct from "the query matched nothing", so the caller
can tell a bad token from an empty result.
"""

from __future__ import annotations

import logging
from types import TracebackType
from typing import Any, Self

import httpx

from .types import JiraAuthMode, JiraCreds, JiraProject

logger = logging.getLogger(__name__)

# Jira caps /search at 100 regardless of what you ask for.
MAX_PAGE_SIZE = 100


class JiraUnavailable(Exception):
    """Jira could not be reached or refused the credentials (spec 90). Carries an
    HTTP status when there was one (None = transport/timeout)."""

    def __init__(self, message: str, status: int | None = None):
        self.status = status
        super().__init__(message)


class JiraClient:
    """One authenticated session against one Jira instance.

    Use as a context manager for anything that makes more than a single call:

        with JiraClient(creds) as jira:
            for page in ...:
                jira.search(jql, start_at=page)
    """

    def __init__(self, creds: JiraCreds):
        self.creds = creds
        self._http: httpx.Client | None = None

    # --- lifecycle ---

    def __enter__(self) -> Self:
        self._http = self._build()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if self._http is not None:
            self._http.close()
            self._http = None

    def _build(self) -> httpx.Client:
        # PAT (Bearer) is the Jira DC idiom and wins when set; basic auth is the
        # fallback for instances with tokens disabled.
        kwargs: dict[str, Any] = {}
        headers = {"Accept": "application/json"}
        if self.creds.auth_mode is JiraAuthMode.PAT:
            headers["Authorization"] = f"Bearer {self.creds.credential}"
        else:
            kwargs["auth"] = (self.creds.username, self.creds.credential)
        return httpx.Client(
            base_url=f"{self.base}/rest/api/2",
            headers=headers,
            timeout=self.creds.timeout_seconds,
            verify=self.creds.verify_ssl,
            **kwargs,
        )

    @property
    def base(self) -> str:
        return self.creds.base_url.rstrip("/")

    @property
    def http(self) -> httpx.Client:
        """The live client, opening a single-call one when used outside a `with`."""
        if self._http is None:
            self._http = self._build()
        return self._http

    # --- transport ---

    def _check(self, response: httpx.Response, what: str) -> Any:
        if response.status_code == 401:
            hint = (
                "the personal access token"
                if self.creds.auth_mode is JiraAuthMode.PAT
                else "the username / password"
            )
            raise JiraUnavailable(f"Jira rejected the credentials (401) — check {hint}", 401)
        if response.status_code == 403:
            raise JiraUnavailable("the Jira account lacks permission (403)", 403)
        if response.status_code >= 300:
            raise JiraUnavailable(
                f"Jira {what} -> {response.status_code}: {response.text[:200]}",
                response.status_code,
            )
        return response.json()

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            response = self.http.get(path, params=params)
        except httpx.HTTPError as exc:
            raise JiraUnavailable(f"could not reach Jira: {exc}") from exc
        return self._check(response, path)

    # --- reads ---

    def check_connection(self) -> dict[str, str]:
        """Hit /myself — the cheapest authenticated call — to confirm URL + credential.
        Returns the service-account identity so the UI can show who it connected as."""
        me = self.get("/myself")
        return {
            "account": me.get("name") or me.get("key") or "",
            "display_name": me.get("displayName", ""),
        }

    def list_projects(self) -> list[JiraProject]:
        raw = self.get("/project")
        projects = [
            JiraProject(
                key=p["key"],
                name=p.get("name", p["key"]),
                id=str(p.get("id", "")),
                project_type=p.get("projectTypeKey", ""),
            )
            for p in raw
            if p.get("key")
        ]
        return sorted(projects, key=lambda p: p.key)

    def field_catalog(self) -> dict[str, dict[str, Any]]:
        """Jira /field → {id: {name, schema_type, schema_items, schema_key, is_custom}}.

        `schema_key` (Jira's `schema.custom`) is the load-bearing one: it is the
        field's plugin TYPE — `com.pyxis.greenhopper.jira:gh-sprint` and friends —
        and it is identical on every Jira instance. Identifying Sprint, Epic Link
        and the board rank keys through it is what makes the importer work against
        an instance it has never seen, instead of against hardcoded ids.
        """
        catalog: dict[str, dict[str, Any]] = {}
        for entry in self.get("/field"):
            fid = entry.get("id")
            if not fid:
                continue
            schema = entry.get("schema") or {}
            catalog[fid] = {
                "name": entry.get("name", fid),
                "schema_type": schema.get("type", ""),
                "schema_items": schema.get("items", ""),
                "schema_key": schema.get("custom", ""),
                "is_custom": bool(entry.get("custom")),
            }
        return catalog

    def search(
        self,
        jql: str,
        *,
        start_at: int = 0,
        max_results: int = MAX_PAGE_SIZE,
        fields: list[str] | None = None,
        expand: list[str] | None = None,
    ) -> dict[str, Any]:
        """One page of a JQL search. `total` is the full match count, so callers can
        page and show progress."""
        payload: dict[str, Any] = {
            "jql": jql,
            "startAt": start_at,
            "maxResults": min(max_results, MAX_PAGE_SIZE),
            "fields": fields or ["*all"],
        }
        if expand:
            payload["expand"] = expand
        try:
            response = self.http.post("/search", json=payload)
        except httpx.HTTPError as exc:
            raise JiraUnavailable(f"could not reach Jira: {exc}") from exc
        if response.status_code == 400:
            # Jira answers a bad JQL with 400 + an errorMessages array — surface it
            # as a value error the router turns into a clean 422, not a 500.
            raise ValueError(_jql_error(response))
        return self._check(response, "search")

    def vocabulary(self, path: str) -> list[dict[str, Any]]:
        """One of Jira's instance-wide vocabulary endpoints — `/issuetype`,
        `/status`, `/priority`, `/issueLinkType`, `/resolution`.

        Captured into the snapshot so the mapping step offers the instance's REAL
        vocabularies. Spec 90 had no equivalent and fell back to English lookup
        tables (`{"blocker": …, "critical": …}`, `"in progress" -> in_progress`),
        which is precisely what tied it to one Jira.
        """
        raw = self.get(path)
        # /issueLinkType wraps its list; the others return a bare array.
        if isinstance(raw, dict):
            for value in raw.values():
                if isinstance(value, list):
                    return value
            return []
        return raw if isinstance(raw, list) else []

    def project_versions(self, project_key: str) -> list[dict[str, Any]]:
        """Fix versions — the source for the versions → releases mapping."""
        raw = self.get(f"/project/{project_key}/versions")
        return raw if isinstance(raw, list) else []

    def project_components(self, project_key: str) -> list[dict[str, Any]]:
        raw = self.get(f"/project/{project_key}/components")
        return raw if isinstance(raw, list) else []

    def issue_changelog(self, key: str, *, start_at: int = 0, max_results: int = 100) -> dict[str, Any]:
        """A page of one issue's change history. Replaying it gives imported issues
        a real activity trail and real cycle-time data, instead of every state
        change appearing to have happened at import o'clock."""
        return self.get(f"/issue/{key}/changelog", {"startAt": start_at, "maxResults": max_results})

    def issue_comments(self, key: str, *, start_at: int = 0, max_results: int = 100) -> dict[str, Any]:
        """A page of one issue's comments.

        `/search` inlines only the first N comments per issue and reports the real
        count in `total`. Spec 90 took the inline list at face value, so a ticket
        with 87 comments imported 20 and nobody was told. Downloads page this
        whenever the inline container is short.
        """
        return self.get(f"/issue/{key}/comment", {"startAt": start_at, "maxResults": max_results})

    def issue_worklogs(self, key: str, *, start_at: int = 0, max_results: int = 100) -> dict[str, Any]:
        """A page of one issue's worklogs — truncated inline exactly like comments."""
        return self.get(f"/issue/{key}/worklog", {"startAt": start_at, "maxResults": max_results})

    def fetch_binary(self, url: str) -> bytes:
        """An attachment's bytes. The content URL is absolute and outside /rest/api/2,
        so it bypasses the base URL but keeps this client's auth and TLS settings."""
        try:
            response = self.http.get(url, follow_redirects=True)
        except httpx.HTTPError as exc:
            raise JiraUnavailable(f"could not download {url}: {exc}") from exc
        if response.status_code >= 300:
            raise JiraUnavailable(
                f"Jira attachment -> {response.status_code}", response.status_code
            )
        return response.content

    def field_option_sets(self, project_key: str) -> dict[str, list[str]]:
        """The CONFIGURED option set per field for a project (spec 90) — the field
        SPEC, not values sampled from issues, so a select's full option list shows
        even for options no ticket currently uses.

        Sources: `createmeta` `allowedValues` (unioned across issue types) and
        `/project/{key}/statuses`. Best-effort — a failure yields what it has, so a
        newer Jira that has retired `createmeta` still previews off sampled values.
        """
        options: dict[str, set[str]] = {}
        try:
            meta = self.get(
                "/issue/createmeta",
                {"projectKeys": project_key, "expand": "projects.issuetypes.fields"},
            )
            for project in meta.get("projects") or []:
                for issuetype in project.get("issuetypes") or []:
                    for fid, spec in (issuetype.get("fields") or {}).items():
                        values = _option_strings(spec.get("allowedValues") or [])
                        if values:
                            options.setdefault(fid, set()).update(values)
        except JiraUnavailable:
            logger.warning(
                "createmeta unavailable for %s — options fall back to sampled values", project_key
            )
        try:
            names = {
                str(status["name"])
                for issuetype in self.get(f"/project/{project_key}/statuses") or []
                for status in issuetype.get("statuses") or []
                if status.get("name")
            }
            if names:
                options["status"] = names
        except JiraUnavailable:
            logger.warning("project statuses unavailable for %s", project_key)
        return {fid: sorted(values) for fid, values in options.items()}

    def browse_url(self, issue_key: str) -> str:
        """The human Jira URL for an issue — the web-link target when a linked issue
        has not been imported into Radd."""
        return f"{self.base}/browse/{issue_key}"


def browse_url(creds: JiraCreds, issue_key: str) -> str:
    """`JiraClient.browse_url` without opening a connection — link building only."""
    return f"{creds.base_url.rstrip('/')}/browse/{issue_key}"


def _jql_error(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"invalid JQL ({response.status_code})"
    messages = body.get("errorMessages") or []
    return "; ".join(messages) if messages else f"invalid JQL ({response.status_code})"


def _option_strings(allowed: list[Any]) -> list[str]:
    out: list[str] = []
    for av in allowed or []:
        if isinstance(av, dict):
            value = av.get("value") or av.get("name")
            if value:
                out.append(str(value))
    return out
