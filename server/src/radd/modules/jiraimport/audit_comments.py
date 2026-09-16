"""Read-only, body-free historical comment visibility report for operators.

Run with the configured database: python -m radd.modules.jiraimport.audit_comments
The transaction is READ ONLY; there is deliberately no apply option. Provenance
is the exact run's snapshot and Jira comment ID, never a body/name heuristic.
Missing provenance is reported as unknown, never declared safe.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from collections import Counter
from enum import StrEnum

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import SessionLocal
from radd.modules.comments import service as comments
from radd.modules.comments.types import CommentVisibility

from .issuemap import comment_is_internal
from .models import JiraImportRecord, JiraRun
from .snapshot import store
from .types import LedgerAction, LedgerEntity


class ReviewAction(StrEnum):
    MAKE_INTERNAL = "make_internal"
    REVIEW_AUDIENCE = "review_restricted_audience"
    UNKNOWN = "source_unavailable"
    MISSING = "target_missing"
    NONE = "no_change_indicated"


def assess(source: dict | None, target: dict | None) -> ReviewAction:
    if target is None:
        return ReviewAction.MISSING
    if source is None:
        return ReviewAction.UNKNOWN
    if source.get("visibility"):
        # Even existing team restrictions need an explicit source-to-target
        # mapping review; matching a group name is not proof of equal audiences.
        return ReviewAction.REVIEW_AUDIENCE
    if comment_is_internal(source) and target["visibility"] != CommentVisibility.INTERNAL:
        return ReviewAction.MAKE_INTERNAL
    return ReviewAction.NONE


async def report_rows(session: AsyncSession, run_ids: list[uuid.UUID] | None = None):
    after = 0
    while True:
        query = select(JiraImportRecord, JiraRun.snapshot_id).join(
            JiraRun, JiraRun.id == JiraImportRecord.run_id
        ).where(
            JiraImportRecord.entity_type == LedgerEntity.COMMENT,
            JiraImportRecord.action == LedgerAction.CREATED,
            JiraImportRecord.id > after,
        ).order_by(JiraImportRecord.id).limit(store.PAGE_ROWS)
        if run_ids:
            query = query.where(JiraImportRecord.run_id.in_(run_ids))
        rows = list((await session.execute(query)).all())
        if not rows:
            return
        ids = [uuid.UUID(record.entity_id) for record, _ in rows]
        targets = await comments.comment_audiences(session, ids)
        # Cache only this bounded window: many comments share one issue.
        sources = {}
        for record, snapshot_id in rows:
            jira_key, separator, comment_id = record.subject.rpartition("#")
            key = (snapshot_id, jira_key)
            if key not in sources:
                issue = await store.get_issue(session, snapshot_id, jira_key) if snapshot_id and separator else None
                sources[key] = {
                    str(c.get("id")): c
                    for c in (((issue.payload.get("fields") or {}).get("comment") or {}).get("comments") or [])
                } if issue else {}
            source = sources[key].get(comment_id)
            target = targets.get(uuid.UUID(record.entity_id))
            action = assess(source, target)
            yield {
                "record_id": record.id,
                "run_id": str(record.run_id),
                "snapshot_id": str(snapshot_id) if snapshot_id else None,
                "source": record.subject,
                "comment_id": record.entity_id,
                "current": target,
                "source_restriction": source.get("visibility") if source else None,
                "action": action.value,
            }
        after = rows[-1][0].id


async def main(run_ids: list[uuid.UUID]) -> None:
    counts = Counter()
    async with SessionLocal() as session:
        # First statement: PostgreSQL enforces this, including accidental writes
        # in a future service dependency. Repeatable snapshot keeps the report coherent.
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        print(json.dumps({"kind": "scope", "read_only": True,
                          "run_ids": [str(value) for value in run_ids],
                          "limitation": "Only ledgered imports are covered. Missing snapshots are unknown; legacy imports without a ledger require separate reconciliation."}))
        async for row in report_rows(session, run_ids):
            counts[row["action"]] += 1
            if row["action"] != ReviewAction.NONE:
                print(json.dumps(row))
    print(json.dumps({"kind": "summary", "counts": counts, "writes": 0}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", type=uuid.UUID, action="append", default=[],
                        help="Limit to this import run (repeatable); default: all ledgered runs")
    args = parser.parse_args()
    asyncio.run(main(args.run_id))
