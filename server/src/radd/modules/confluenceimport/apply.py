"""Writing one page — the seam a dry run and a real run share (spec 117).

`commit=False` resolves EVERYTHING identically and only skips the service call, so
a dry run's counts are facts rather than estimates: "3 spaces and 214 pages will
be created" is measured by doing all the work except the write.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth.types import Permission
from radd.modules.pages import service as pages_service
from radd.modules.pages.schemas import PageCreate, PageUpdate

from . import ledger
from .ledger import LedgerEntity
from .storage import ConvertContext, convert
from .types import Problem, UpsertAction

#: Everything a re-import overwrites on an existing page — and therefore the only
#: columns its before-image needs.
REFRESHED_COLUMNS = ("title", "body", "parent_id", "position", "version", "updated_by")

#: The permission set the importer passes into `pages`. It is what unlocks the
#: author/timestamp/external-identity overrides; without it every imported page
#: would be authored by whoever ran the import and stamped today.
IMPORT_PERMISSIONS = frozenset({Permission.PAGE_MANAGE})


@dataclass(slots=True)
class PageOutcome:
    action: UpsertAction = UpsertAction.CREATE
    page_id: uuid.UUID | None = None
    problems: list[Problem] = field(default_factory=list)
    page_refs: set[str] = field(default_factory=set)
    attachment_refs: set[str] = field(default_factory=set)


async def upsert_page(
    session: AsyncSession,
    *,
    space_id: uuid.UUID,
    parent_id: uuid.UUID | None,
    title: str,
    body_storage: str,
    position: float,
    external_source: str,
    external_id: str,
    author_id: uuid.UUID,
    created_at,
    updated_at,
    context: ConvertContext,
    actor_id: uuid.UUID,
    run_id: uuid.UUID | None,
    commit: bool,
) -> PageOutcome:
    """Create the page, or refresh the one a previous run made from the same
    foreign row. That lookup — not the ledger — is what makes re-import an upsert,
    because it survives a rollback and outlives the plugin."""
    outcome = PageOutcome()
    converted = convert(body_storage, context)
    outcome.problems.extend(converted.problems)
    outcome.page_refs = converted.page_refs
    outcome.attachment_refs = converted.attachment_refs

    existing = await pages_service.find_by_external(session, external_source, external_id)
    outcome.action = UpsertAction.UPDATE if existing is not None else UpsertAction.CREATE
    if not commit:
        outcome.page_id = existing.id if existing else None
        return outcome

    if existing is not None:
        await ledger.updated(
            session, run_id, LedgerEntity.PAGE, existing.id,
            ledger.snapshot_of(existing, REFRESHED_COLUMNS), subject=title,
        )
        await pages_service.update_page(
            session,
            existing.id,
            PageUpdate(
                title=title, body=converted.markdown, parent_id=parent_id,
                position=position, author_id=author_id, updated_at=updated_at,
            ),
            actor_id,
            permissions=IMPORT_PERMISSIONS,
        )
        outcome.page_id = existing.id
        return outcome

    page = await pages_service.create_page(
        session,
        PageCreate(
            space_id=space_id,
            parent_id=parent_id,
            title=title,
            body=converted.markdown,
            position=position,
            author_id=author_id,
            created_at=created_at,
            updated_at=updated_at,
            external_source=external_source,
            external_id=external_id,
        ),
        actor_id,
        permissions=IMPORT_PERMISSIONS,
    )
    await ledger.created(session, run_id, LedgerEntity.PAGE, page.id, subject=title)
    outcome.page_id = page.id
    return outcome


async def write_history(
    session: AsyncSession,
    page_id: uuid.UUID,
    revisions: list[dict],
    *,
    resolve_author,
    actor_id: uuid.UUID,
    run_id: uuid.UUID | None,
    commit: bool,
    context: ConvertContext,
) -> int:
    """Write revisions 1..N-1 as `page_versions` rows.

    `PageVersion` holds the PREVIOUS content — version N's row is written when N+1
    becomes current — so the live body is revision N and history is everything
    below it. Getting this backwards yields a History tab whose newest entry
    duplicates the current body while revision 1 is silently lost.
    """
    if not commit:
        return len(revisions)
    written = 0
    for revision in revisions:
        author_id = resolve_author(revision.get("author", "")) or actor_id
        body = convert(revision.get("body", ""), context).markdown
        row = await pages_service.write_version(
            session,
            page_id,
            version=int(revision.get("version", 0)),
            title=revision.get("title", ""),
            body=body,
            author_id=author_id,
            created_at=_parsed(revision.get("when", "")),
            permissions=IMPORT_PERMISSIONS,
        )
        await ledger.created(session, run_id, LedgerEntity.VERSION, row.id)
        written += 1
    return written


def _parsed(value: str):
    """Confluence timestamps are ISO-8601 with an offset. A value we cannot read
    is left to the column default rather than guessed at."""
    from datetime import datetime

    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
