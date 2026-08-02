"""Discovery service for the Jira import wizard (specs 90, 100) — the async seam
over the synchronous `JiraClient`, plus schema inference.

Read-only: is a connection alive, what projects exist, and what does a JQL slice
look like. Every entry point takes the `JiraCreds` of a resolved connection, so
nothing here reads deploy configuration or touches the database.
"""

from __future__ import annotations

import asyncio

from . import inference
from .client import JiraClient, JiraUnavailable
from .types import InferredField, InferredType, JiraCreds, JiraProject


async def check_connection(creds: JiraCreds) -> tuple[bool, str, str]:
    """(ok, account, error) for one connection. Never raises: an unreachable Jira
    or a stale token is a state to render, not a 500."""
    if not creds.usable:
        return False, "", "the connection is missing a base URL or credential"
    try:
        who = await asyncio.to_thread(_check, creds)
    except JiraUnavailable as exc:
        return False, "", str(exc)
    return True, who["account"], ""


def _check(creds: JiraCreds) -> dict[str, str]:
    with JiraClient(creds) as jira:
        return jira.check_connection()


async def list_projects(creds: JiraCreds) -> list[JiraProject]:
    return await asyncio.to_thread(_list_projects, creds)


def _list_projects(creds: JiraCreds) -> list[JiraProject]:
    with JiraClient(creds) as jira:
        return jira.list_projects()


async def preview(
    creds: JiraCreds, jql: str, sample_size: int, project_key: str | None = None
) -> tuple[int, list[InferredField]]:
    """Run the JQL, sample up to `sample_size` issues, and infer the inbound schema
    against the live field catalog. Returns (total_matches, fields).

    All three reads share ONE client: spec 90 ran them in parallel threads, which
    cost three TLS handshakes to save about two round trips. The option sets — the
    field SPEC — replace the sample-derived distinct values, so the value-mapping
    table shows every configured option, not just the ones a sampled ticket used.
    """
    return await asyncio.to_thread(_preview, creds, jql, sample_size, project_key)


def _preview(
    creds: JiraCreds, jql: str, sample_size: int, project_key: str | None
) -> tuple[int, list[InferredField]]:
    with JiraClient(creds) as jira:
        result = jira.search(jql, start_at=0, max_results=sample_size)
        catalog = jira.field_catalog()
        option_sets = jira.field_option_sets(project_key) if project_key else {}
    issues = result.get("issues") or []
    total = int(result.get("total", len(issues)))
    fields = inference.infer_schema(issues, catalog)
    _apply_option_sets(fields, option_sets)
    return total, fields


def _apply_option_sets(fields: list[InferredField], option_sets: dict[str, list[str]]) -> None:
    """Replace each select field's sampled distinct values with its full configured
    option set (unioned with the sample, so an option in use but absent from the
    spec — a since-removed one — is still offered)."""
    for f in fields:
        spec = option_sets.get(f.jira_id)
        if not spec:
            continue
        f.distinct_values = sorted(set(spec) | set(f.distinct_values or []))
        # A field the sample thought was empty/text but that HAS a configured option
        # set is really a select — surface the options.
        if f.inferred_type not in (InferredType.SELECT, InferredType.MULTI_SELECT):
            f.inferred_type = InferredType.SELECT
