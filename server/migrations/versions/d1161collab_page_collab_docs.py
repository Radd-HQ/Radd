"""RADD-1161 (spec 122): the live document's persisted state

One row per co-edited page: the encoded Yjs state and the `pages.version` it
corresponds to. A room resumes a row whose version matches the page's current
one and discards any other — the page was written by something that was not
the room, and the markdown is the truth. Cascades with the page.

Revision ID: d1161collab
Revises: d1009projdesc
"""

import sqlalchemy as sa
from alembic import op

revision = "d1161collab"
down_revision = "d1009projdesc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "page_collab_docs",
        sa.Column(
            "page_id",
            sa.Uuid(),
            sa.ForeignKey("pages.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("state", sa.LargeBinary(), nullable=False),
        sa.Column("page_version", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("page_collab_docs")
