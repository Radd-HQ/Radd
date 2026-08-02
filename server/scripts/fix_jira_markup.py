"""Back-fill already-imported comment + item-description bodies from Jira wiki markup
to Markdown (the importer now does this for new imports — this fixes old rows).

Rows are converted with ``assume_jira=False``: only bodies carrying an unambiguous
Jira construct ({code}, ||tables||, {panel}, hN. …) are touched, so natively-authored
Markdown (which legitimately contains `*emphasis*` and `# headings`) is never
corrupted by the ambiguous rules. `--assume-jira` lifts that gate — use it only on a
database where ALL content came from a Jira import. Dry-run by default:

    uv run python scripts/fix_jira_markup.py            # report only
    uv run python scripts/fix_jira_markup.py --apply    # write changes + a rollback file

The rollback file (JSON of {table: {id: original_body}}) lets you revert.
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone

from sqlalchemy import text

sys.path.insert(0, os.path.dirname(__file__))
from jira_markup import jira_to_markdown  # noqa: E402

from radd.db import SessionLocal  # noqa: E402

TARGETS = [
    ("comments", "body"),
    ("work_items", "description"),
]


async def main(apply: bool, assume_jira: bool) -> None:
    rollback: dict[str, dict[str, str]] = {}
    async with SessionLocal() as session:
        for table, column in TARGETS:
            rows = (
                await session.execute(text(f"SELECT id, {column} FROM {table}"))
            ).all()
            changed: list[tuple[str, str, str]] = []
            for row_id, body in rows:
                converted = jira_to_markdown(body, assume_jira=assume_jira)
                if converted != (body or ""):
                    changed.append((str(row_id), body or "", converted))
            print(f"{table}.{column}: {len(changed)} / {len(rows)} rows would change")
            if changed[:2]:
                sample_id, before, after = changed[0]
                print(f"  e.g. {sample_id}\n    BEFORE: {before[:120]!r}\n    AFTER:  {after[:120]!r}")
            if apply and changed:
                rollback[table] = {row_id: before for row_id, before, _ in changed}
                for row_id, _, converted in changed:
                    await session.execute(
                        text(f"UPDATE {table} SET {column} = :v WHERE id = :id"),
                        {"v": converted, "id": row_id},
                    )
        if apply:
            await session.commit()
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            path = os.path.join(os.environ.get("CLAUDE_JOB_DIR", "/tmp"), f"tmp/jira_markup_rollback-{stamp}.json")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as handle:
                json.dump(rollback, handle)
            print(f"APPLIED. Rollback written to {path}")
        else:
            print("DRY RUN — re-run with --apply to write changes.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--assume-jira",
        action="store_true",
        help="convert every row, not just ones with unambiguous Jira markup "
        "(only safe when ALL content came from a Jira import)",
    )
    args = parser.parse_args()
    asyncio.run(main(args.apply, args.assume_jira))
