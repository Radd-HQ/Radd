"""RADD-958/961: mail_sources, mail_senders, mail_rules.

Email was the last subsystem reading its configuration from the environment on
every use. Sign-in (spec 110), Storage (102) and AI (101) are all rows seeded
once from env; this brings mail in line, which is what makes "point Radd at your
own support@company.com" configuration rather than a deployment.

`mail_rules` is the part that did not exist in any form. Where a message landed
was one line — a plus-address tag if it named a real project, else one
instance-wide default — so "mail to pipeline@ opens in DEV" was inexpressible,
and "decide from what the email says" doubly so.

Nothing is seeded here. Seeding reads env at STARTUP, not in a migration: a
migration runs once per database while seeding must be idempotent per boot, and
putting credentials in a migration file is how they end up in git history.

Revision ID: d958mailcfg
Revises: d952mailmsg
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d958mailcfg"
down_revision = "d952mailmsg"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mail_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("address", sa.String(320), nullable=False, server_default=""),
        sa.Column("secret", sa.Text(), nullable=False, server_default=""),
        sa.Column("host", sa.String(255), nullable=False, server_default=""),
        sa.Column("port", sa.Integer(), nullable=False, server_default="993"),
        sa.Column("username", sa.String(320), nullable=False, server_default=""),
        sa.Column("folder", sa.String(120), nullable=False, server_default="INBOX"),
        sa.Column(
            "default_project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "mail_senders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("from_address", sa.String(320), nullable=False, server_default=""),
        sa.Column("reply_to", sa.String(320), nullable=False, server_default=""),
        sa.Column("host", sa.String(255), nullable=False, server_default=""),
        sa.Column("port", sa.Integer(), nullable=False, server_default="587"),
        sa.Column("username", sa.String(320), nullable=False, server_default=""),
        sa.Column("secret", sa.Text(), nullable=False, server_default=""),
        sa.Column("starttls", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "mail_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mail_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("rule_type", sa.String(32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("position", sa.Float(), nullable=False, server_default="0"),
        sa.Column("config", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_mail_sources_default_project", "mail_sources", ["default_project_id"])
    op.create_index("ix_mail_rules_source_id", "mail_rules", ["source_id"])
    op.create_index("ix_mail_rules_source_position", "mail_rules", ["source_id", "position"])


def downgrade() -> None:
    op.drop_table("mail_rules")
    op.drop_table("mail_senders")
    op.drop_table("mail_sources")
