"""`/spend` comments on a GitHub pull request, mirrored into the linked issue (RADD-1261).

GitHub has no time tracking, so the entry lives in a comment (`spend.py` reads
it). Two delivery shapes feed this module:

- **one comment at a time** — the `issue_comment` / `pull_request_review_comment`
  / `pull_request_review` webhooks: `reconcile_comment` mirrors THAT comment's
  lines, with deletion narrowed to that comment's ids (`id_prefix`), so the
  PR's other comments are untouched; `remove_comment` drops them;
- **every comment of a PR** — the backfill: `reconcile_pull_request` walks the
  PR's issue comments and review comments and reconciles the whole scope.

Authors: GitHub hides emails, so the mapping comes from the identity map —
filled by hand in Settings, or automatically from a push's commit-author emails
(`record_commit_authors`). With a token, `GET /users/{login}` adds the public
email when the user set one.
"""

import logging
from datetime import date, datetime
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.modules.vcs import timemirror
from radd.modules.vcs.ids import pr_external_id
from radd.modules.vcs.types import VcsProvider

from . import spend
from .backfill import api_headers
from .models import GithubConnection, GithubRepo

logger = logging.getLogger(__name__)


def comment_date(value: str) -> date:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


async def _entries_for_comments(
    session: AsyncSession,
    repo_name: str,
    comments: list[dict[str, Any]],
    emails: dict[str, str],
) -> tuple[list[timemirror.SourceEntry], int]:
    """Comments → entries. A line whose duration does not parse is counted and
    skipped — a typo is not time."""
    entries: list[timemirror.SourceEntry] = []
    invalid = 0
    for comment in comments:
        login = str((comment.get("user") or {}).get("login") or "")
        comment_id = comment.get("id")
        if not login or comment_id is None:
            continue
        created = comment_date(str(comment.get("created_at") or datetime.now().isoformat()))
        for command in spend.parse_spend(str(comment.get("body") or "")):
            try:
                seconds = await timemirror.parse_duration(session, command.duration_text)
            except ValueError:  # the duration grammar raises a ValueError; a typo is not time
                invalid += 1
                continue
            note = command.note
            if command.key_override:
                # The key rides in the note so the seam's per-entry override sees it.
                note = f"{command.key_override} {note}".strip()
            entries.append(
                timemirror.SourceEntry(
                    external_id=spend.comment_entry_id(repo_name, comment_id, command.position),
                    seconds=seconds,
                    spent_on=command.spent_on or created,
                    author_username=login,
                    author_email=emails.get(login, ""),
                    note=note,
                )
            )
    return entries, invalid


async def _public_emails(connection: GithubConnection, logins: set[str]) -> dict[str, str]:
    """`GET /users/{login}` → public email, with a token only: anonymous calls
    are rate-limited to nothing useful, and most profiles hide the address
    anyway — the identity map is the real answer for GitHub."""
    if not connection.api_token or not logins:
        return {}
    emails: dict[str, str] = {}
    async with httpx.AsyncClient(
        headers=api_headers(connection), verify=connection.verify_ssl,
        timeout=settings.github_http_timeout_seconds,
    ) as client:
        for login in logins:
            try:
                response = await client.get(f"{connection.api_url}/users/{login}")
                if response.status_code < 400:
                    emails[login] = str(response.json().get("email") or "")
            except httpx.HTTPError as exc:
                logger.info("github: user %s lookup failed: %s", login, exc)
    return emails


def _note_prefix(number: int | str, title: str) -> str:
    return f"Logged on #{number} {title}".strip()[:2000]


async def reconcile_comment(
    session: AsyncSession,
    connection: GithubConnection,
    repo: GithubRepo | None,
    *,
    repo_name: str,
    number: int | str,
    title: str,
    body: str,
    comment: dict[str, Any],
) -> dict[str, Any]:
    """One comment's `/spend` lines, created or edited. Deletion is limited to
    this comment's own ids."""
    login = str((comment.get("user") or {}).get("login") or "")
    emails = await _public_emails(connection, {login} if login else set())
    entries, invalid = await _entries_for_comments(session, repo_name, [comment], emails)
    category_id = await timemirror.default_category_id(
        session, repo.time_category_id if repo is not None else None
    )
    report = await timemirror.reconcile(
        session,
        provider=VcsProvider.GITHUB,
        connection_id=connection.id,
        scope=pr_external_id(repo_name, number),
        ref_texts=[title, body],
        entries=entries,
        category_id=category_id,
        note_prefix=_note_prefix(number, title),
        id_prefix=spend.comment_prefix(repo_name, comment.get("id", "")),
    )
    return {**report.as_dict(), "invalid": invalid}


async def remove_comment(
    session: AsyncSession,
    connection: GithubConnection,
    *,
    repo_name: str,
    number: int | str,
    comment_id: int | str,
) -> dict[str, Any]:
    """A deleted comment takes its entries with it — an empty reconcile under
    the comment's id prefix."""
    report = await timemirror.reconcile(
        session,
        provider=VcsProvider.GITHUB,
        connection_id=connection.id,
        scope=pr_external_id(repo_name, number),
        ref_texts=[],
        entries=[],
        category_id=None,
        note_prefix="",
        id_prefix=spend.comment_prefix(repo_name, comment_id),
    )
    return report.as_dict()


async def unspend(
    session: AsyncSession,
    connection: GithubConnection,
    *,
    repo_name: str,
    number: int | str,
    login: str,
) -> dict[str, Any]:
    deleted = await timemirror.remove_author_entries(
        session,
        provider=VcsProvider.GITHUB,
        connection_id=connection.id,
        scope=pr_external_id(repo_name, number),
        username=login,
    )
    return {"deleted": deleted}


async def reconcile_pull_request(
    session: AsyncSession,
    connection: GithubConnection,
    repo: GithubRepo | None,
    *,
    repo_name: str,
    number: int | str,
    title: str,
    body: str,
    head_branch: str,
    comments: list[dict[str, Any]],
) -> timemirror.MirrorReport:
    """Every comment of a PR at once (the backfill): a whole-scope reconcile."""
    logins = {str((c.get("user") or {}).get("login") or "") for c in comments} - {""}
    emails = await _public_emails(connection, logins)
    entries, _invalid = await _entries_for_comments(session, repo_name, comments, emails)
    category_id = await timemirror.default_category_id(
        session, repo.time_category_id if repo is not None else None
    )
    return await timemirror.reconcile(
        session,
        provider=VcsProvider.GITHUB,
        connection_id=connection.id,
        scope=pr_external_id(repo_name, number),
        ref_texts=[head_branch, title, body],
        entries=entries,
        category_id=category_id,
        note_prefix=_note_prefix(number, title),
    )


async def record_commit_authors(
    session: AsyncSession, connection: GithubConnection, payload: dict[str, Any]
) -> int:
    """A push carries `commits[].author.{email, username}` — the one place
    GitHub shows an email next to a login. Each match records an identity-map
    row (`resolve_author` does), so later `/spend` comments by that login
    resolve without anyone typing the mapping. Returns how many resolved."""
    seen: set[str] = set()
    resolved = 0
    for commit in payload.get("commits") or []:
        author = commit.get("author") or {}
        login = str(author.get("username") or "").strip()
        email = str(author.get("email") or "").strip()
        if not login or not email or login.lower() in seen:
            continue
        seen.add(login.lower())
        if await timemirror.resolve_author(
            session, provider=VcsProvider.GITHUB, connection_id=connection.id, username=login, email=email
        ):
            resolved += 1
    return resolved
