"""RADD-1295: people have pictures.

`users.avatar_blob` + `avatar_blob_host_id` name an uploaded picture (stored by
the `avatars` module through the attachments blob API); `avatar_idp_url` is the
identity provider's picture. The backfill copies the picture every existing
SSO identity already recorded in its claims, so Google/GitHub users get their
face now rather than at their next sign-in.

Revision ID: d1295avatars
Revises: d1279mfaticket
"""
import sqlalchemy as sa
from alembic import op

revision = "d1295avatars"
down_revision = "d1279mfaticket"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_blob", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("avatar_blob_host_id", sa.Uuid(), nullable=True))
    op.add_column("users", sa.Column("avatar_idp_url", sa.String(1024), nullable=True))
    op.execute("""
        UPDATE users AS u SET avatar_idp_url = picked.picture
        FROM (
            SELECT DISTINCT ON (user_id) user_id, claims->>'picture' AS picture
            FROM user_identities
            WHERE claims->>'picture' LIKE 'https://%'
              AND length(claims->>'picture') <= 1024
            ORDER BY user_id, updated_at DESC
        ) AS picked
        WHERE picked.user_id = u.id
    """)


def downgrade() -> None:
    op.drop_column("users", "avatar_idp_url")
    op.drop_column("users", "avatar_blob_host_id")
    op.drop_column("users", "avatar_blob")
