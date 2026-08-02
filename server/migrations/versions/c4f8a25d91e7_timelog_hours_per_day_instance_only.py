"""timelog_hours_per_day becomes instance-only (spec 67 follow-up)

User direction: no per-project hours-per-day — one global value, so a "1d"
duration means the same thing on every timesheet row and cycle handle. The
registry now declares the key instance-only (writes at project scope 409) and
`resolve` ignores narrower scopes for it; this defensively drops any existing
project-scope override rows (the live DB has none — verified).

Hand-written: autogenerate against this DB proposes a false-positive drop of
the `ix_doc_pages_fts` expression index. Idempotent re-run (no rows → no-op).

Revision ID: c4f8a25d91e7
Revises: a7c2e19b4f30

"""
from alembic import op


revision = 'c4f8a25d91e7'
down_revision = 'a7c2e19b4f30'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "DELETE FROM scoped_settings"
        " WHERE key = 'timelog_hours_per_day' AND scope = 'project'"
    )


def downgrade() -> None:
    # Deleted project overrides are not recoverable; nothing structural changed.
    pass
