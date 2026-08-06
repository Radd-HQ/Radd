"""RADD-922: one item payload shape — discard the stream that had fourteen.

The events table is APPEND-ONLY, so rows written before this keep their old
payload forever. Three consumers query them directly — `reporting/timeline.py`
runs SQL against `payload["item"]["project"]["id"]`, the search indexer rebuilds
from the stream, and `items/history.py` renders the History tab from it — and
none of them can read both shapes without a compatibility branch in every one.

Compatibility branches were explicitly rejected (owner decision, 2026-08-06):
"I don't care about losing the events table entirely, I would rather not have
workarounds." So the old rows go. What that costs, said plainly:

* **The History tab and the audit log start empty.** They are projections of the
  stream; there is no second copy.
* **Cycle/throughput reporting loses its history** for the same reason.
* **The search index is NOT affected** — it is its own table, and the startup
  sweep repairs it from `work_items` regardless.

The identity sequence is NOT restarted. Consumer offsets point at ids that no
longer exist, which is harmless: every new event gets a HIGHER id, so each
consumer resumes cleanly at the next one rather than replaying an empty table.
Restarting the sequence would put new events BELOW the stored offsets and every
consumer would skip them silently — the one failure mode worth spelling out
here, because it would look like the workers had simply stopped.
"""

from alembic import op

revision = "d922payload"
down_revision = "d116actas"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Not TRUNCATE: it takes an ACCESS EXCLUSIVE lock and resets nothing we want
    # reset. DELETE keeps the sequence where it is, which is the property the
    # consumer offsets depend on.
    op.execute("DELETE FROM events")


def downgrade() -> None:
    # Deliberately empty. The rows are gone; a downgrade cannot invent them, and
    # pretending otherwise would be worse than saying so.
    pass
