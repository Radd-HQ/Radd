"""GitLab hosts and projects as rows (RADD-1253) — the Forgejo/GitHub shape.

The env secret becomes a one-time seed (`gitlab.service.seed_from_env`), so an
instance that ran the spec-31 connector from `RADD_GITLAB_WEBHOOK_SECRET` keeps
verifying its hook across the upgrade.
"""

from alembic import op
import sqlalchemy as sa

revision = "d1253gitlabconn"
down_revision = "d1258timemirror"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "gitlab_connections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("api_token", sa.String(500), nullable=False),
        sa.Column("webhook_secret", sa.String(200), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("verify_ssl", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "gitlab_repos",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "connection_id",
            sa.Uuid(),
            sa.ForeignKey("gitlab_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("full_name", sa.String(300), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("default_branch", sa.String(200), nullable=False),
        sa.Column("last_backfill_at", sa.DateTime(), nullable=True),
        sa.Column(
            "time_category_id",
            sa.Uuid(),
            sa.ForeignKey("work_categories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("connection_id", "full_name"),
    )
    op.create_index("ix_gitlab_repos_connection_id", "gitlab_repos", ["connection_id"])
    op.create_index("ix_gitlab_repos_project_id", "gitlab_repos", ["project_id"])


def downgrade():
    op.drop_table("gitlab_repos")
    op.drop_table("gitlab_connections")
