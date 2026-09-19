"""Mirror time logged on merge/pull requests into worklogs (RADD-1258).

- `worklogs` gains provenance (`external_source`, `external_scope`, `external_id`)
  under a partial UNIQUE index, so a source entry lands on one row however many
  times it is delivered or backfilled.
- `vcs_user_links`: provider account → Radd user, per connection.
- `vcs_pending_worklogs`: entries parked because their author has no Radd account.
- `forgejo_repos` / `github_repos` gain `time_category_id`, the category a
  mirrored worklog carries (NULL = the instance's Development).
"""

from alembic import op
import sqlalchemy as sa

revision = "d1258timemirror"
down_revision = "d1233pagepath"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("worklogs", sa.Column("external_source", sa.String(20), nullable=False, server_default=""))
    op.add_column("worklogs", sa.Column("external_scope", sa.String(200), nullable=False, server_default=""))
    op.add_column("worklogs", sa.Column("external_id", sa.String(200), nullable=False, server_default=""))
    op.create_index(
        "uq_worklogs_external",
        "worklogs",
        ["external_source", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id <> ''"),
    )

    op.create_table(
        "vcs_user_links",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("external_username", sa.String(200), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("matched_by", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "provider", "connection_id", "external_username", name="uq_vcs_user_links_account"
        ),
    )
    op.create_index("ix_vcs_user_links_connection_id", "vcs_user_links", ["connection_id"])
    op.create_index("ix_vcs_user_links_user_id", "vcs_user_links", ["user_id"])

    op.create_table(
        "vcs_pending_worklogs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("external_scope", sa.String(200), nullable=False),
        sa.Column("external_id", sa.String(200), nullable=False),
        sa.Column("external_username", sa.String(200), nullable=False),
        sa.Column("external_email", sa.String(320), nullable=False, server_default=""),
        sa.Column("item_id", sa.Uuid(), sa.ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category_id", sa.Uuid(), sa.ForeignKey("work_categories.id", ondelete="SET NULL"), nullable=True),
        sa.Column("worked_on", sa.Date(), nullable=False),
        sa.Column("time_spent_seconds", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("provider", "external_id", name="uq_vcs_pending_worklogs_entry"),
    )
    op.create_index("ix_vcs_pending_worklogs_connection_id", "vcs_pending_worklogs", ["connection_id"])
    op.create_index("ix_vcs_pending_worklogs_external_scope", "vcs_pending_worklogs", ["external_scope"])
    op.create_index("ix_vcs_pending_worklogs_external_username", "vcs_pending_worklogs", ["external_username"])
    op.create_index("ix_vcs_pending_worklogs_item_id", "vcs_pending_worklogs", ["item_id"])

    for table in ("forgejo_repos", "github_repos"):
        op.add_column(
            table,
            sa.Column(
                "time_category_id",
                sa.Uuid(),
                sa.ForeignKey("work_categories.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )


def downgrade():
    for table in ("forgejo_repos", "github_repos"):
        op.drop_column(table, "time_category_id")
    op.drop_table("vcs_pending_worklogs")
    op.drop_table("vcs_user_links")
    op.drop_index("uq_worklogs_external", table_name="worklogs")
    op.drop_column("worklogs", "external_id")
    op.drop_column("worklogs", "external_scope")
    op.drop_column("worklogs", "external_source")
