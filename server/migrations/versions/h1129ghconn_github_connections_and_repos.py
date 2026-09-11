"""RADD-1129: github connections and repositories as rows

Hand-written like d111fjconn (autogenerate wants to drop the runtime-managed
embeddings tables). The two tables mirror forgejo_connections / forgejo_repos.

Revision ID: h1129ghconn
Revises: h1113commentpage
"""

import sqlalchemy as sa
from alembic import op

revision = "h1129ghconn"
down_revision = "h1113commentpage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "github_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column("api_token", sa.String(length=500), nullable=False),
        sa.Column("webhook_secret", sa.String(length=200), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("verify_ssl", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_github_connections")),
        sa.UniqueConstraint("name", name=op.f("uq_github_connections_name")),
    )
    op.create_table(
        "github_repos",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("full_name", sa.String(length=300), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("default_branch", sa.String(length=200), nullable=False),
        sa.Column("last_backfill_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["github_connections.id"],
            name=op.f("fk_github_repos_connection_id_github_connections"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_github_repos_project_id_projects"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_github_repos")),
        sa.UniqueConstraint(
            "connection_id", "full_name", name=op.f("uq_github_repos_connection_id_full_name")
        ),
    )
    op.create_index(op.f("ix_github_repos_connection_id"), "github_repos", ["connection_id"])
    op.create_index(op.f("ix_github_repos_project_id"), "github_repos", ["project_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_github_repos_project_id"), table_name="github_repos")
    op.drop_index(op.f("ix_github_repos_connection_id"), table_name="github_repos")
    op.drop_table("github_repos")
    op.drop_table("github_connections")
