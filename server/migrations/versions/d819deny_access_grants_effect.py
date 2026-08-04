"""d819deny: access_grants.effect — deny precedence (RADD-819)

One column, server_default 'allow'. Opt-in and inert until a deny row is
written: behaviour is byte-identical on the day this lands. The precedence
(specificity first, deny on ties) lives in access/resolution.py and the
relations semantics doc.

Revision ID: d819deny
Revises: d816verbs
Create Date: 2026-08-04
"""
import sqlalchemy as sa
from alembic import op

revision = 'd819deny'
down_revision = 'd816verbs'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'access_grants',
        sa.Column('effect', sa.String(length=5), nullable=False, server_default='allow'),
    )


def downgrade() -> None:
    # Deny rows have no allow-model representation; dropping the column drops
    # the restriction they expressed — a WIDENING, so it is deliberate-only.
    op.drop_column('access_grants', 'effect')
