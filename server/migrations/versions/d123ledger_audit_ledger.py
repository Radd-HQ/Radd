"""RADD-1169 (spec 123): the audit ledger columns on `events`

Three derived columns so the trail can be filtered and searched without a
sequential scan over every payload: `project_id` ("everything in project X"),
`entity_label` (what the thing was called when it happened — survives the
row's deletion), and `search_text` (the event's words, the entity's label,
the changed fields and their old/new values). `emit` fills them from the
subject refs a payload already carries.

Indexes: a btree on project_id; a trigram GIN over search_text, guarded on the
`pg_trgm` extension the way `acca7433a9b7` guarded pgvector (without it the
ILIKE still works, unindexed); a GIN over `payload -> 'changes'` so
"every change to the assignee field" is a containment probe.

Backfill: best effort, in SQL, from the same payload keys `emit` reads — the
live trail stays searchable for what happened before this migration.

Revision ID: d123ledger
Revises: d1161collab
"""

import logging

import sqlalchemy as sa
from alembic import op

revision = "d123ledger"
down_revision = "d1161collab"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

_UUID_RE = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"


def _uuid_or_null(expr: str) -> str:
    return f"CASE WHEN ({expr}) ~ '{_UUID_RE}' THEN ({expr})::uuid ELSE NULL END"


def upgrade() -> None:
    op.add_column("events", sa.Column("project_id", sa.Uuid(), nullable=True))
    op.add_column("events", sa.Column("entity_label", sa.String(length=300), nullable=True))
    op.add_column("events", sa.Column("search_text", sa.Text(), nullable=True))
    op.create_index("ix_events_project_id", "events", ["project_id"], unique=False)
    op.execute(
        "CREATE INDEX ix_events_changes ON events USING gin ((payload -> 'changes') jsonb_path_ops)"
    )

    bind = op.get_bind()
    available = bind.execute(
        sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'pg_trgm'")
    ).scalar()
    if available:
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        op.execute(
            "CREATE INDEX ix_events_search_trgm ON events USING gin (search_text gin_trgm_ops)"
        )
    else:
        logger.warning(
            "pg_trgm is not available on this server — audit text search stays unindexed "
            "(a sequential ILIKE). Install the extension and create "
            "ix_events_search_trgm by hand; no re-migration is needed."
        )

    # --- backfill (best effort) ---------------------------------------------
    project = "COALESCE({}, {}, {}, {})".format(
        _uuid_or_null("payload -> 'project' ->> 'id'"),
        _uuid_or_null("payload -> 'item' -> 'project' ->> 'id'"),
        _uuid_or_null("payload -> 'item' ->> 'project_id'"),
        _uuid_or_null("payload ->> 'project_id'"),
    )
    ref = "COALESCE(payload -> events.entity_type, payload)"
    label = f"""
        LEFT(COALESCE(
            NULLIF(CONCAT_WS(' ', {ref} ->> 'key', COALESCE(NULLIF({ref} ->> 'title', ''), NULLIF({ref} ->> 'name', ''))), ''),
            NULLIF({ref} ->> 'name', ''),
            NULLIF({ref} ->> 'title', ''),
            NULLIF({ref} ->> 'email', ''),
            NULLIF({ref} ->> 'version', ''),
            NULLIF({ref} ->> 'label', ''),
            NULLIF({ref} ->> 'full_name', ''),
            NULLIF({ref} ->> 'url', ''),
            NULLIF({ref} ->> 'key', '')
        ), 300)
    """
    op.execute(
        sa.text(
            f"""
            UPDATE events SET
                project_id = {project},
                entity_label = {label}
            WHERE payload IS NOT NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE events SET search_text = LEFT(
                CONCAT_WS(' ',
                    REPLACE(REPLACE(event_type, '.', ' '), '_', ' '),
                    entity_label,
                    (
                        SELECT string_agg(
                            CONCAT_WS(' ', c ->> 'field', c ->> 'name', c ->> 'from', c ->> 'to',
                                      c ->> 'added', c ->> 'removed'),
                            ' '
                        )
                        FROM jsonb_array_elements(
                            CASE WHEN jsonb_typeof(payload -> 'changes') = 'array'
                                 THEN payload -> 'changes' ELSE '[]'::jsonb END
                        ) AS c
                    )
                ), 4000)
            """
        )
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_events_search_trgm")
    op.execute("DROP INDEX IF EXISTS ix_events_changes")
    op.drop_index("ix_events_project_id", table_name="events")
    op.drop_column("events", "search_text")
    op.drop_column("events", "entity_label")
    op.drop_column("events", "project_id")
