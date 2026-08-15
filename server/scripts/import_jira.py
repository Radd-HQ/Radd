#!/usr/bin/env python3
"""Import a Jira sample export (scripts/sample_data/*.json) into Radd via the REST API.

Pure API client — no radd imports, no direct DB. Dogfoods the same endpoints the UI uses.

    uv run python scripts/import_jira.py --file scripts/sample_data/jira_sample.json \
        --email admin@example.com --password ...

Spec 86: the workspace entity is gone — projects/fields/cycles are global.
Auth: --token radd_pat_... (Bearer PAT) or --email/--password (session login).
Env fallbacks: RADD_API, RADD_TOKEN, RADD_EMAIL, RADD_PASSWORD.
Exit codes: 0 = imported (or skipped: project key already present), 1 = errors occurred.
"""

from __future__ import annotations

import argparse
import json
import os
import mimetypes
import secrets
import sys
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from jira_markup import jira_to_markdown, replace_attachment_embeds

import httpx

DEFAULT_API = "http://localhost:8000/api/v1"
TITLE_MAX = 500
HTTP_CONFLICT = 409
HTTP_NOT_FOUND = 404
# A create's transaction can commit just after its response is sent, so an immediately
# following request may briefly not see the new row. Retry dependent POSTs on 404.
RETRY_ATTEMPTS = 4
RETRY_DELAY_SECONDS = 0.2

# Imported items keep their original Jira number 1:1 (Jira SKY-1004 -> Radd SKY-1004),
# so the native key IS the Jira key — no separate bookkeeping field. Original author +
# timestamp are set natively (project.manage import overrides), not as a text prefix.


def jira_number(jira_key: str) -> int:
    """'SKY-1004' -> 1004 — the number becomes the Radd item number."""
    return int(jira_key.rpartition("-")[2])


class FieldType(StrEnum):
    SELECT = "select"
    MULTI_SELECT = "multi_select"


class Entity(StrEnum):
    PROJECT = "project"
    USERS = "users"
    FIELDS = "fields"
    CYCLES = "cycles"
    ITEMS = "items"
    COMMENTS = "comments"
    WORKLOGS = "worklogs"
    LINKS = "links"
    WEBLINKS = "web_links"
    ATTACHMENTS = "attachments"


class ImportError_(Exception):
    """Fatal setup problem (bad credentials, unreachable API, malformed file)."""


@dataclass
class Tally:
    created: int = 0
    existing: int = 0
    errors: int = 0


@dataclass
class Report:
    tallies: dict[Entity, Tally] = field(default_factory=lambda: {e: Tally() for e in Entity})
    warnings: list[str] = field(default_factory=list)
    error_details: list[str] = field(default_factory=list)

    def warn(self, message: str) -> None:
        self.warnings.append(message)
        print(f"  warning: {message}", file=sys.stderr)

    def error(self, entity: Entity, message: str) -> None:
        self.tallies[entity].errors += 1
        self.error_details.append(f"{entity}: {message}")
        print(f"  ERROR: {entity}: {message}", file=sys.stderr)

    @property
    def total_errors(self) -> int:
        return sum(t.errors for t in self.tallies.values())

    def print_summary(self) -> None:
        header = f"{'entity':<12} {'created':>8} {'existing':>9} {'errors':>7}"
        print("\n== import summary " + "=" * (len(header) - 18))
        print(header)
        print("-" * len(header))
        for entity, tally in self.tallies.items():
            print(f"{entity:<12} {tally.created:>8} {tally.existing:>9} {tally.errors:>7}")
        if self.warnings:
            print(f"\n{len(self.warnings)} warning(s) — see stderr above.")
        if self.error_details:
            print(f"{len(self.error_details)} error(s):")
            for detail in self.error_details:
                print(f"  - {detail}")


class Api:
    """Thin authenticated wrapper over the Radd REST API."""

    def __init__(self, base_url: str, token: str | None, email: str | None, password: str | None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.client = httpx.Client(base_url=base_url, headers=headers, timeout=30.0)
        if not token:
            if not (email and password):
                raise ImportError_("provide --token or both --email and --password")
            response = self.client.post("/auth/login", json={"email": email, "password": password})
            if response.status_code >= 300:
                raise ImportError_(f"login failed ({response.status_code}): {response.text}")
        me = self.request("GET", "/auth/me")
        self.actor_id: str = me["id"]

    def request(
        self, method: str, path: str, *, json: Any = None, params: dict[str, Any] | None = None
    ) -> Any:
        """Raise on any non-2xx. Use `try_request` where 409 is tolerated."""
        status, data = self.try_request(method, path, json=json, params=params)
        if status >= 300:
            raise ImportError_(f"{method} {path} -> {status}: {data}")
        return data

    def try_request(
        self, method: str, path: str, *, json: Any = None, params: dict[str, Any] | None = None
    ) -> tuple[int, Any]:
        response = self.client.request(method, path, json=json, params=params)
        try:
            data = response.json()
        except ValueError:
            data = response.text
        return response.status_code, data

    def upload(
        self, path: str, filename: str, content: bytes, *, form: dict[str, str] | None = None
    ) -> tuple[int, Any]:
        """Multipart file upload (attachments) — `form` carries the polymorphic
        parent fields the spec-102 endpoint requires (RADD-1094)."""
        mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        response = self.client.post(
            path, files={"file": (filename, content, mime)}, data=form or {}
        )
        try:
            data = response.json()
        except ValueError:
            data = response.text
        return response.status_code, data

    def post_dependent(self, path: str, *, json: Any) -> tuple[int, Any]:
        """POST that references a row created by the previous request (see RETRY_ATTEMPTS)."""
        status, data = self.try_request("POST", path, json=json)
        for _ in range(RETRY_ATTEMPTS - 1):
            if status != HTTP_NOT_FOUND:
                break
            time.sleep(RETRY_DELAY_SECONDS)
            status, data = self.try_request("POST", path, json=json)
        return status, data


@dataclass
class Context:
    """Everything resolved during setup that item/comment rows need."""

    api: Api
    report: Report
    project_id: str = ""
    users_by_email: dict[str, dict[str, str]] = field(default_factory=dict)  # email -> {id, name}
    field_defs: dict[str, dict[str, Any]] = field(default_factory=dict)  # key -> definition
    state_by_category: dict[str, str] = field(default_factory=dict)  # category -> state id
    item_ids: dict[str, str] = field(default_factory=dict)  # jira_key -> item id
    cycles_by_name: dict[str, str] = field(default_factory=dict)  # cycle name -> cycle id
    timelogging: bool = False  # project has time logging enabled (worklogs/estimates import)
    # --attachments-dir: <dir>/<JIRA-KEY>/<filename> files, pre-downloaded by the caller.
    # Uploaded per item; `!filename!` embeds in descriptions/comments rewrite to the
    # uploaded URL so old screenshots actually render.
    attachments_dir: str | None = None


# --- setup passes ---


def project_key_exists(ctx: Context, key: str) -> bool:
    projects = ctx.api.request("GET", "/projects")
    return any(p["key"].upper() == key.upper() for p in projects)


def create_project(ctx: Context, key: str, name: str) -> None:
    created = ctx.api.request("POST", "/projects", json={"key": key, "name": name})
    ctx.project_id = created["id"]
    ctx.report.tallies[Entity.PROJECT].created += 1


def import_users(ctx: Context, users: list[dict[str, str]]) -> None:
    existing_by_email: dict[str, dict[str, Any]] | None = None
    for user in users:
        payload = {
            "email": user["email"],
            "name": user["name"],
            "password": secrets.token_urlsafe(24),
            "instance_role": "member",
        }
        status, data = ctx.api.try_request("POST", "/users", json=payload)
        if status in (200, 201):
            ctx.users_by_email[user["email"]] = {"id": data["id"], "name": data["name"]}
            ctx.report.tallies[Entity.USERS].created += 1
        elif status == HTTP_CONFLICT:
            if existing_by_email is None:
                existing_by_email = {u["email"]: u for u in ctx.api.request("GET", "/users")}
            found = existing_by_email.get(user["email"])
            if found is None:
                ctx.report.error(Entity.USERS, f"{user['email']}: 409 but not listed by GET /users")
                continue
            ctx.users_by_email[user["email"]] = {"id": found["id"], "name": found["name"]}
            ctx.report.tallies[Entity.USERS].existing += 1
        else:
            ctx.report.error(Entity.USERS, f"{user['email']}: {status} {data}")
    # Spec 86: no membership seat needed — any active user holds the global member floor.


def import_fields(ctx: Context, file_fields: list[dict[str, Any]]) -> None:
    for spec in file_fields:
        payload = {
            "project_id": None,  # global: shared by every project we import
            "key": spec["key"],
            "name": spec["name"],
            "type": spec["type"],
            "required": bool(spec.get("required", False)),
            "options": spec.get("options"),
            "source": spec.get("source", "user"),
        }
        status, data = ctx.api.try_request("POST", "/fields", json=payload)
        if status in (200, 201):
            ctx.report.tallies[Entity.FIELDS].created += 1
        elif status == HTTP_CONFLICT:
            ctx.report.tallies[Entity.FIELDS].existing += 1
        else:
            ctx.report.error(Entity.FIELDS, f"{spec['key']}: {status} {data}")
    # Effective definitions drive value filtering: the API has no field-update endpoint,
    # so a pre-existing definition (409 above) keeps its own option list.
    listed = ctx.api.request("GET", "/fields")
    ctx.field_defs = {d["key"]: d for d in listed}
    for spec in file_fields:
        existing = ctx.field_defs.get(spec["key"])
        missing = set(spec.get("options") or []) - set((existing or {}).get("options") or [])
        if existing and missing:
            ctx.report.warn(
                f"field '{spec['key']}' already exists without options {sorted(missing)}; "
                "values using them will be dropped (no field-update API)"
            )


def enable_timelogging(ctx: Context) -> None:
    status, data = ctx.api.try_request(
        "PUT", f"/projects/{ctx.project_id}/timelogging", json={"enabled": True}
    )
    if status in (200, 201):
        ctx.timelogging = True
    else:
        ctx.report.warn(f"could not enable timelogging: {status} {data} (worklogs skipped)")


def import_cycles(ctx: Context, cycles: list[dict[str, Any]]) -> None:
    """Find-or-create global cycles by name (sprints span projects, so a second
    project's import reuses the cycles the first created)."""
    existing = {c["name"]: c["id"] for c in ctx.api.request("GET", "/cycles")}
    for cycle in cycles:
        name = cycle["name"]
        if name in existing:
            ctx.cycles_by_name[name] = existing[name]
            ctx.report.tallies[Entity.CYCLES].existing += 1
            continue
        payload = {
            "name": name,
            "start_date": cycle.get("start_date"),
            "end_date": cycle.get("end_date"),
            "goal": cycle.get("goal", ""),
        }
        status, data = ctx.api.try_request("POST", "/cycles", json=payload)
        if status in (200, 201):
            ctx.cycles_by_name[name] = data["id"]
            ctx.report.tallies[Entity.CYCLES].created += 1
        else:
            ctx.report.error(Entity.CYCLES, f"{name}: {status} {data}")


def map_states(ctx: Context) -> None:
    params = {"project_id": ctx.project_id}
    states = ctx.api.request("GET", "/states", params=params)
    for _ in range(RETRY_ATTEMPTS - 1):
        if states:  # default states appear with the project; empty means we read too early
            break
        time.sleep(RETRY_DELAY_SECONDS)
        states = ctx.api.request("GET", "/states", params=params)
    for state in sorted(states, key=lambda s: (not s["is_default"], s["position"])):
        ctx.state_by_category.setdefault(state["category"], state["id"])


# --- row mapping ---


def clean_custom_fields(ctx: Context, jira_key: str, values: dict[str, Any]) -> dict[str, Any]:
    """Keep only values the effective field definitions will accept."""
    cleaned: dict[str, Any] = {}
    for key, value in values.items():
        definition = ctx.field_defs.get(key)
        if definition is None:
            ctx.report.warn(f"{jira_key}: dropping value for unknown field '{key}'")
            continue
        options = definition.get("options") or []
        if definition["type"] == FieldType.SELECT and value not in options:
            ctx.report.warn(f"{jira_key}: dropping {key}={value!r} (not in options)")
            continue
        if definition["type"] == FieldType.MULTI_SELECT:
            values_list = value if isinstance(value, list) else [value]
            kept = [v for v in values_list if v in options]
            value = values_list
            if dropped := sorted(set(value) - set(kept)):
                ctx.report.warn(f"{jira_key}: dropping {key} values {dropped} (not in options)")
            if not kept:
                continue
            value = kept
        cleaned[key] = value
    return cleaned


def _user_id(ctx: Context, email: str | None, jira_key: str, role: str) -> str | None:
    if not email:
        return None
    if entry := ctx.users_by_email.get(email):
        return entry["id"]
    ctx.report.warn(f"{jira_key}: {role} {email} not in file's users; left unset")
    return None


def item_payload(ctx: Context, issue: dict[str, Any], parent_id: str | None) -> dict[str, Any]:
    jira_key = issue["jira_key"]
    payload = {
        "project_id": ctx.project_id,
        "number": jira_number(jira_key),  # preserve the Jira ID 1:1 -> native key
        "title": issue["title"][:TITLE_MAX],
        "description": jira_to_markdown(issue.get("description")),
        "kind": issue.get("kind", "issue"),
        "parent_id": parent_id,
        "state_id": ctx.state_by_category.get(issue["status_category"]),
        "priority": issue.get("priority", "normal"),
        "assignee_id": _user_id(ctx, issue.get("assignee_email"), jira_key, "assignee"),
        # Reporter (spec 30) preserved from Jira; None => the importing user.
        "reporter_id": _user_id(ctx, issue.get("reporter_email"), jira_key, "reporter"),
        "team_id": None,
        # Sprint -> cycle (global, spans projects). Unknown name => unset.
        "cycle_id": ctx.cycles_by_name.get(issue.get("cycle_name") or ""),
        "created_at": issue.get("created"),  # preserve the original filing time
        "target_date": issue.get("target_date"),
        "labels": issue.get("labels") or [],
        "custom_fields": clean_custom_fields(ctx, jira_key, issue.get("custom_fields") or {}),
    }
    if payload["reporter_id"] is None:
        # Omit rather than send null: an EXPLICIT null now means "no reporter"
        # (spec 62 public submits); omitting keeps "unknown => the importing user".
        del payload["reporter_id"]
    return payload


def upload_attachments(ctx: Context, item_id: str, jira_key: str) -> dict[str, str]:
    """Upload <attachments-dir>/<JIRA-KEY>/* to the item; filename -> download URL."""
    if not ctx.attachments_dir:
        return {}
    issue_dir = os.path.join(ctx.attachments_dir, jira_key)
    if not os.path.isdir(issue_dir):
        return {}
    urls: dict[str, str] = {}
    for filename in sorted(os.listdir(issue_dir)):
        path = os.path.join(issue_dir, filename)
        if not os.path.isfile(path):
            continue
        with open(path, "rb") as handle:
            # POST /attachments with the polymorphic parent (RADD-1094): the old
            # /items/{id}/attachments alias died with RADD-895, so this uploaded
            # into a 404 for every --attachments-dir run since.
            status, data = ctx.api.upload(
                "/attachments", filename, handle.read(),
                form={"entity_type": "item", "entity_id": str(item_id)},
            )
        if status in (200, 201):
            urls[filename] = f"/attachments/{data['id']}"
            ctx.report.tallies[Entity.ATTACHMENTS].created += 1
        else:
            ctx.report.error(Entity.ATTACHMENTS, f"{jira_key}/{filename}: {status} {data}")
    return urls


def create_item(ctx: Context, issue: dict[str, Any], parent_id: str | None) -> None:
    jira_key = issue["jira_key"]
    category = issue.get("status_category")
    if category not in ctx.state_by_category:
        ctx.report.error(Entity.ITEMS, f"{jira_key}: no state for category '{category}'")
        return
    status, data = ctx.api.post_dependent("/items", json=item_payload(ctx, issue, parent_id))
    if status not in (200, 201):
        ctx.report.error(Entity.ITEMS, f"{jira_key}: {status} {data}")
        return
    ctx.item_ids[jira_key] = data["id"]
    ctx.report.tallies[Entity.ITEMS].created += 1
    # Attachments must exist before embeds can point at them: upload, then re-render
    # the description from the RAW wiki text with `!file!` embeds resolved.
    attachment_urls = upload_attachments(ctx, data["id"], jira_key)
    raw_description = issue.get("description") or ""
    if attachment_urls and any(name in raw_description for name in attachment_urls):
        rewritten = jira_to_markdown(replace_attachment_embeds(raw_description, attachment_urls))
        patch_status, patch_data = ctx.api.try_request(
            "PATCH", f"/items/{data['id']}", json={"description": rewritten}
        )
        if patch_status not in (200, 201):
            ctx.report.error(Entity.ATTACHMENTS, f"{jira_key}: embed rewrite {patch_status}")
    import_comments(ctx, data["id"], issue, attachment_urls)
    import_web_links(ctx, data["id"], issue)
    if ctx.timelogging:
        import_worklogs(ctx, data["id"], issue)
        set_estimate(ctx, data["id"], issue)


def import_web_links(ctx: Context, item_id: str, issue: dict[str, Any]) -> None:
    """External / cross-project Jira links become web links (spec 'related links')."""
    for wl in issue.get("web_links") or []:
        status, data = ctx.api.post_dependent(
            f"/items/{item_id}/web-links",
            json={"url": wl["url"], "title": wl.get("title", ""),
                  "category": wl.get("category", "external")},
        )
        if status in (200, 201):
            ctx.report.tallies[Entity.WEBLINKS].created += 1
        else:
            ctx.report.error(Entity.WEBLINKS, f"{issue['jira_key']}: {status} {data}")


def import_item_links(ctx: Context, links: list[dict[str, Any]]) -> None:
    """Second pass (all items exist): create intra-project blocks/relates/duplicates
    links. Radd rejects the symmetric mirror of `relates` with 409 — tolerated."""
    for link in links:
        source_id = ctx.item_ids.get(link["source_key"])
        if source_id is None or link["target_key"] not in ctx.item_ids:
            continue  # an endpoint wasn't imported (e.g. errored) — skip
        payload = {
            "target_number": jira_number(link["target_key"]),
            "link_type": link["link_type"],
        }
        status, data = ctx.api.try_request("POST", f"/items/{source_id}/links", json=payload)
        if status in (200, 201):
            ctx.report.tallies[Entity.LINKS].created += 1
        elif status == HTTP_CONFLICT:
            ctx.report.tallies[Entity.LINKS].existing += 1  # mirror/duplicate — fine
        else:
            ctx.report.error(Entity.LINKS, f"{link['source_key']}->{link['target_key']}: {status} {data}")


def import_comments(
    ctx: Context, item_id: str, issue: dict[str, Any], attachment_urls: dict[str, str] | None = None
) -> None:
    for comment in issue.get("comments") or []:
        entry = ctx.users_by_email.get(comment["author_email"])
        # Native author + timestamp (project.manage overrides) — no text prefix needed.
        body = replace_attachment_embeds(comment["body"], attachment_urls or {})
        payload: dict[str, Any] = {"body": jira_to_markdown(body)}
        if entry:
            payload["author_id"] = entry["id"]
        if comment.get("created"):
            payload["created_at"] = comment["created"]
        status, data = ctx.api.post_dependent(f"/items/{item_id}/comments", json=payload)
        if status in (200, 201):
            ctx.report.tallies[Entity.COMMENTS].created += 1
        else:
            ctx.report.error(Entity.COMMENTS, f"{issue['jira_key']}: {status} {data}")


def import_worklogs(ctx: Context, item_id: str, issue: dict[str, Any]) -> None:
    """POST each Jira worklog, preserving the original author (project.manage
    override) and the date it was worked (so timesheets distribute correctly)."""
    for wl in issue.get("worklogs") or []:
        entry = ctx.users_by_email.get(wl.get("author_email") or "")
        payload = {
            "time_spent": wl["time_spent"],  # Jira duration text, e.g. "3h 30m"
            "worked_on": wl.get("worked_on"),  # YYYY-MM-DD; None => today at the API
            "note": (wl.get("note") or "")[:2000],
        }
        if entry:
            payload["author_id"] = entry["id"]
        if wl.get("created"):
            payload["created_at"] = wl["created"]  # when it was logged (history)
        status, data = ctx.api.post_dependent(f"/items/{item_id}/worklogs", json=payload)
        if status in (200, 201):
            ctx.report.tallies[Entity.WORKLOGS].created += 1
        else:
            ctx.report.error(Entity.WORKLOGS, f"{issue['jira_key']}: {status} {data}")


def set_estimate(ctx: Context, item_id: str, issue: dict[str, Any]) -> None:
    estimate = issue.get("original_estimate")
    if estimate and estimate.strip().rstrip("mhdw0 ") == "":
        return  # zero-duration ("0m"/"0h") — Jira's default; nothing to record
    if estimate:
        status, data = ctx.api.try_request(
            "PUT", f"/items/{item_id}/estimate", json={"estimate": estimate}
        )
        if status not in (200, 201):
            ctx.report.warn(f"{issue['jira_key']}: estimate {estimate!r} -> {status} {data}")


def import_items(ctx: Context, issues: list[dict[str, Any]]) -> None:
    roots = [i for i in issues if not i.get("parent_jira_key")]
    children = [i for i in issues if i.get("parent_jira_key")]
    for issue in roots:  # pass 1: epics and standalone issues
        create_item(ctx, issue, parent_id=None)
    for issue in children:  # pass 2: children resolve parents from pass 1
        parent_id = ctx.item_ids.get(issue["parent_jira_key"])
        if parent_id is None:
            ctx.report.warn(
                f"{issue['jira_key']}: parent {issue['parent_jira_key']} not imported; "
                "creating without parent"
            )
        create_item(ctx, issue, parent_id=parent_id)


# --- CLI ---


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--file", required=True, help="path to jira_sample*.json")
    parser.add_argument("--api", default=os.environ.get("RADD_API", DEFAULT_API))
    parser.add_argument("--token", default=os.environ.get("RADD_TOKEN"), help="radd_pat_... PAT")
    parser.add_argument("--email", default=os.environ.get("RADD_EMAIL"))
    parser.add_argument("--password", default=os.environ.get("RADD_PASSWORD"))
    parser.add_argument(
        "--project-key",
        default=None,
        help="override the file's project key (to re-import when the original key exists)",
    )
    parser.add_argument(
        "--reuse-project",
        action="store_true",
        help="import into an EXISTING project of this key instead of skipping "
        "(states/fields kept; use after wiping its items to replace contents)",
    )
    parser.add_argument(
        "--attachments-dir",
        default=None,
        help="directory of pre-downloaded Jira attachments (<dir>/<JIRA-KEY>/<file>) "
        "— uploaded per item, `!file!` embeds rewritten",
    )
    return parser.parse_args(argv)


def resolve_existing_project(ctx: Context, key: str) -> None:
    projects = ctx.api.request("GET", "/projects")
    match = next((p for p in projects if p["key"].upper() == key.upper()), None)
    if match is None:
        raise ImportError_(f"--reuse-project: no project '{key}' found")
    ctx.project_id = match["id"]
    ctx.report.tallies[Entity.PROJECT].existing += 1


def load_export(path: str) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        raise ImportError_(f"cannot read {path}: {exc}") from exc
    missing = {"project", "fields", "users", "issues"} - set(data)
    if missing:
        raise ImportError_(f"{path}: missing top-level keys {sorted(missing)}")
    return data


def run(args: argparse.Namespace) -> int:
    export = load_export(args.file)
    report = Report()
    ctx = Context(
        api=Api(args.api, token=args.token, email=args.email, password=args.password),
        report=report,
        attachments_dir=args.attachments_dir,
    )
    project_key = args.project_key or export["project"]["key"]
    exists = project_key_exists(ctx, project_key)
    if exists and not args.reuse_project:
        report.tallies[Entity.PROJECT].existing += 1
        report.warn(
            f"project key '{project_key}' already exists; "
            "skipping import (pass --project-key for a new key, or --reuse-project to add to it)"
        )
        report.print_summary()
        return 0
    print(f"importing {args.file} -> project '{project_key}'")
    import_users(ctx, export["users"])
    # Project BEFORE fields: GET /fields answers [] to an actor with no readable
    # project (the RADD-788 member floor), and on a virgin instance no project
    # exists yet — so fields created here would be invisible to the very next
    # listing and every value would be dropped as "unknown field".
    if exists:
        resolve_existing_project(ctx, project_key)
    else:
        create_project(ctx, project_key, export["project"]["name"])
    import_fields(ctx, export["fields"])
    map_states(ctx)
    if export.get("timelogging"):
        enable_timelogging(ctx)
    import_cycles(ctx, export.get("cycles") or [])
    import_items(ctx, export["issues"])
    import_item_links(ctx, export.get("item_links") or [])
    report.print_summary()
    return 1 if report.total_errors else 0


def main() -> int:
    try:
        return run(parse_args(sys.argv[1:]))
    except ImportError_ as exc:
        print(f"fatal: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
