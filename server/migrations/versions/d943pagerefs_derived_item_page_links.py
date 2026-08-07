"""RADD-943: item_page_links.derived — a page's linked issues follow its text.

The table held one kind of row: someone typed a key into the panel. It now holds
two, and the flag is what keeps them apart.

    derived = false  the link is user data. A body edit may never remove it.
    derived = true   the link is owned by the page's text, reconciled on every
                     save from the issue references the body carries.

Existing rows are all manual by definition — every one of them was typed — so
the default is exactly right and no data moves. The derived half starts empty
and fills in as pages are saved; `pages.mentions.reindex_all`, behind
`POST /pages/reindex`, backfills the pages that will not be edited again.

Reversible without loss: dropping the column would leave the derived rows
looking manual, so the downgrade deletes them first. They are derived — the next
save recreates every one.

Revision ID: d943pagerefs
Revises: d929grants
"""

import sqlalchemy as sa
from alembic import op

revision = "d943pagerefs"
down_revision = "d929grants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "item_page_links",
        sa.Column("derived", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.execute("DELETE FROM item_page_links WHERE derived")
    op.drop_column("item_page_links", "derived")
