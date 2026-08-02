"""transition applies_when scoping (spec 107 follow-up)

`workflow_transitions.applies_when` — bare field-condition dicts scoping WHICH
items a row governs (empty = every item; resolution is first-match). Pure
column add; existing rows keep governing everything.

Revision ID: b107appl1es
Revises: a107c0nd1t10n
Create Date: 2026-07-30
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b107appl1es"
down_revision = "a107c0nd1t10n"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workflow_transitions",
        sa.Column(
            "applies_when",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("workflow_transitions", "applies_when")
