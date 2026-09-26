"""Discovery for the Jira import wizard — the async seam over the synchronous
`JiraClient`: is a connection alive, what projects exist, how many issues a JQL
matches. Read-only; takes the `JiraCreds` of a resolved connection."""

from __future__ import annotations

import asyncio

from .client import JiraClient, JiraUnavailable
from .types import JiraCreds, JiraProject


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


async def preview(creds: JiraCreds, jql: str) -> int:
    """The JQL's full match count — the download dialog's "Test JQL". A bad query
    raises ValueError (the router's 422)."""
    return await asyncio.to_thread(_preview, creds, jql)


def _preview(creds: JiraCreds, jql: str) -> int:
    with JiraClient(creds) as jira:
        result = jira.search(jql, max_results=1, fields=["key"])
    return int(result.get("total", len(result.get("issues") or [])))
