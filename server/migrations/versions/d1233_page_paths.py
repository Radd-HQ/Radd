"""Pages keyed by id, addressed by path (RADD-1233).

A slug is unique among LIVE SIBLINGS, not across the space: the id is the key,
the slug is the segment a page contributes to its path, and a path is
unambiguous exactly when siblings differ. `page_path_history` keeps every path a
page has answered to, so a stale link still resolves — exactly.
"""
from alembic import op
import sqlalchemy as sa

revision = "d1233pagepath"
down_revision = "d1226threads"
branch_labels = None
depends_on = None

#: What a root page's parent coalesces to in the sibling index. A NULL parent
#: would make every root page distinct from every other under a plain unique
#: index (NULL != NULL), so root slugs would not be unique at all.
ROOT = "'00000000-0000-0000-0000-000000000000'::uuid"


def upgrade():
    # The human key: one instance-wide sequence, existing pages numbered in the
    # order they were created so the numbers read as history.
    op.execute("CREATE SEQUENCE pages_number_seq")
    op.add_column("pages", sa.Column("number", sa.BigInteger(), nullable=True))
    op.execute(
        "UPDATE pages p SET number = s.n FROM ("
        "SELECT id, row_number() OVER (ORDER BY created_at, id) AS n FROM pages"
        ") s WHERE p.id = s.id"
    )
    op.execute("SELECT setval('pages_number_seq', coalesce((SELECT max(number) FROM pages), 0) + 1, false)")
    op.alter_column(
        "pages", "number", nullable=False, server_default=sa.text("nextval('pages_number_seq')")
    )
    op.create_index("uq_pages_number", "pages", ["number"], unique=True)

    op.drop_constraint("uq_pages_space_slug", "pages", type_="unique")
    op.execute(
        "CREATE UNIQUE INDEX uq_pages_live_sibling_slug ON pages "
        f"(space_id, coalesce(parent_id, {ROOT}), slug) WHERE archived_at IS NULL"
    )
    op.create_table(
        "page_path_history",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("page_id", sa.Uuid(), sa.ForeignKey("pages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("space_id", sa.Uuid(), sa.ForeignKey("page_spaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_page_path_history_page_id", "page_path_history", ["page_id"])
    op.create_index("ix_page_path_history_space_path", "page_path_history", ["space_id", "path"])


def downgrade():
    op.drop_table("page_path_history")
    op.drop_index("uq_pages_number", table_name="pages")
    op.drop_column("pages", "number")
    op.execute("DROP SEQUENCE pages_number_seq")
    op.execute("DROP INDEX uq_pages_live_sibling_slug")
    # Cannot be recreated when two live pages share a name in different parents,
    # or a live page shares one with an archived page; both are the point.
    op.create_unique_constraint("uq_pages_space_slug", "pages", ["space_id", "slug"])
