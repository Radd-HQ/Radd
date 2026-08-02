"""Reconstruct CLOSED item↔cycle stints (spec 56) from the event log.

The migration seeds an OPEN `item_cycle_records` row per current assignment;
this script mines `item.updated` events whose `changes` diff carries a cycle
move and writes the historical CLOSED stints (carryovers, removals), so
`past_cycle` SLQ queries see history from before the feature existed.

Diffs record cycle NAMES, so each name is resolved against the cycles table;
unresolvable names (deleted/renamed cycles) are reported and skipped. Existing
records make reruns safe: a stint whose (item, cycle, removed_at) already
exists is skipped. Dry-run by default:

    uv run python scripts/backfill_cycle_history.py            # report only
    uv run python scripts/backfill_cycle_history.py --apply    # write records
"""

import argparse
import asyncio
import os
import sys
import uuid
from collections import defaultdict

from sqlalchemy import select, text

sys.path.insert(0, os.path.dirname(__file__))
from radd.db import SessionLocal  # noqa: E402
from radd.modules.items import models as _item_models  # noqa: E402,F401 — registers work_items for the FK
from radd.modules.cycles.models import Cycle, ItemCycleRecord  # noqa: E402

EVENTS_SQL = text(
    """
    SELECT e.entity_id::uuid AS item_id, e.created_at, e.payload->'changes' AS changes,
           w.created_at AS item_created_at
    FROM events e
    JOIN work_items w ON w.id = e.entity_id::uuid
    WHERE e.event_type = 'item.updated'
      AND e.payload->'changes' IS NOT NULL
      AND e.payload->'changes' @> '[{"field": "cycle"}]'
    ORDER BY e.created_at ASC
    """
)


async def main(apply: bool) -> None:
    async with SessionLocal() as session:
        cycles = (await session.execute(select(Cycle))).scalars().all()
        by_name = {c.name: c.id for c in cycles}
        existing = {
            (r.item_id, r.cycle_id, r.removed_at)
            for r in (await session.execute(select(ItemCycleRecord))).scalars()
        }
        open_rows = {
            (r.item_id, r.cycle_id): r
            for r in (await session.execute(select(ItemCycleRecord))).scalars()
            if r.removed_at is None
        }

        events = (await session.execute(EVENTS_SQL)).all()
        # Per item: entry time into the cycle it is CURRENTLY in mid-replay.
        entered_at: dict[uuid.UUID, object] = {}
        created, skipped_names, refreshed = 0, defaultdict(int), 0

        for row in events:
            change = next(c for c in row.changes if c["field"] == "cycle")
            from_name, to_name = change.get("from"), change.get("to")
            if from_name is not None:
                cycle_id = by_name.get(from_name)
                if cycle_id is None:
                    skipped_names[from_name] += 1
                else:
                    added = entered_at.get(row.item_id) or row.item_created_at
                    key = (row.item_id, cycle_id, row.created_at)
                    if key not in existing:
                        existing.add(key)
                        created += 1
                        print(f"  stint: item {str(row.item_id)[:8]} in '{from_name}' "
                              f"{added} -> {row.created_at}")
                        if apply:
                            session.add(ItemCycleRecord(
                                item_id=row.item_id, cycle_id=cycle_id,
                                added_at=added, removed_at=row.created_at,
                            ))
            entered_at[row.item_id] = row.created_at
            # Sharpen the migration-seeded OPEN row's added_at to the real entry time.
            if to_name is not None and by_name.get(to_name) is not None:
                open_row = open_rows.get((row.item_id, by_name[to_name]))
                if open_row is not None and open_row.added_at != row.created_at:
                    refreshed += 1
                    if apply:
                        open_row.added_at = row.created_at

        for name, count in sorted(skipped_names.items()):
            print(f"  ! cycle '{name}' no longer exists — {count} stint(s) skipped")
        print(f"{'wrote' if apply else 'would write'} {created} closed stint(s); "
              f"sharpened {refreshed} open added_at stamp(s); "
              f"{sum(skipped_names.values())} skipped (deleted cycles)")
        if apply:
            await session.commit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write records (default: dry-run)")
    args = parser.parse_args()
    asyncio.run(main(args.apply))
