"""Spec 117 — external identity on spaces and pages.

Where a row came from, when something outside Radd made it. The Jira importer
never needed this because `DEV-123` maps onto Radd `DEV-123` and the item KEY is
the external identity; a page has only a UUID and a cosmetic slug, so without a
column the mapping lives in an importer's run ledger — scoped to one run, deleted
by its rollback, gone when the plugin is removed.

The unique index is PARTIAL. Every natively-created row carries the same empty
pair, and a plain unique constraint would permit exactly one of them.

Revision ID: d117extid
Revises: d997mailretry
"""

import sqlalchemy as sa
from alembic import op

revision = "d117extid"
down_revision = "d997mailretry"
branch_labels = None
depends_on = None

_TABLES = ("page_spaces", "pages")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column(
                "external_source",
                sa.String(200),
                nullable=False,
                server_default="",
            ),
        )
        op.add_column(
            table,
            sa.Column(
                "external_id", sa.String(200), nullable=False, server_default=""
            ),
        )
        op.create_index(
            f"uq_{table}_external",
            table,
            ["external_source", "external_id"],
            unique=True,
            postgresql_where=sa.text("external_id <> ''"),
        )


def downgrade() -> None:
    for table in _TABLES:
        op.drop_index(f"uq_{table}_external", table_name=table)
        op.drop_column(table, "external_id")
        op.drop_column(table, "external_source")
