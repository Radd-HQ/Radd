"""sso provider registry + federated identities (spec 110)

Providers move out of the environment into `sso_providers`; `user_identities`
pins each federated login to the IdP's immutable subject so a Google sign-in
lands on the person's existing AD account instead of forking a duplicate.

Nothing is backfilled: the env `oidc_*` settings seed the first provider row at
startup (registry.seed_from_env), which keeps the seeding rule in one place and
lets an admin who deletes that row keep it deleted.

Revision ID: d110ssoprov
Revises: 79554b33d374
Create Date: 2026-08-01

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d110ssoprov"
down_revision = "79554b33d374"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sso_providers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("issuer", sa.String(length=500), nullable=False),
        sa.Column("client_id", sa.String(length=500), nullable=False),
        sa.Column("client_secret", sa.Text(), nullable=False),
        sa.Column("scopes", sa.String(length=500), nullable=False),
        sa.Column("auto_provision", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "allowed_signup_domains",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "require_verified_email", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("group_claim", sa.String(length=100), nullable=False),
        sa.Column("admin_groups", sa.String(length=1000), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sso_providers")),
        sa.UniqueConstraint("name", name=op.f("uq_sso_providers_name")),
    )
    op.create_table(
        "user_identities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column(
            "claims", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["sso_providers.id"],
            name=op.f("fk_user_identities_provider_id_sso_providers"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_identities_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_identities")),
        sa.UniqueConstraint(
            "provider_id", "subject", name=op.f("uq_user_identities_provider_id_subject")
        ),
    )
    op.create_index(
        op.f("ix_user_identities_provider_id"), "user_identities", ["provider_id"], unique=False
    )
    op.create_index(
        op.f("ix_user_identities_user_id"), "user_identities", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_user_identities_user_id"), table_name="user_identities")
    op.drop_index(op.f("ix_user_identities_provider_id"), table_name="user_identities")
    op.drop_table("user_identities")
    op.drop_table("sso_providers")
