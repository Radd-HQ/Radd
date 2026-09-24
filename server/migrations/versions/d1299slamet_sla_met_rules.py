"""RADD-1299: SLA targets say what "met" means; policies can filter on the
reporter's team.

Every existing policy gets today's two rules as its defaults (response =
first_reply, resolution = done) and empty lists, so nothing it evaluates
changes.

Revision ID: d1299slamet
Revises: d1295avatars
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "d1299slamet"
down_revision = "d1295avatars"
branch_labels = None
depends_on = None

_LISTS = (
    "reporter_team_ids", "response_state_ids", "response_team_ids",
    "resolution_state_ids", "resolution_team_ids",
)


def upgrade() -> None:
    for column in _LISTS:
        op.add_column("sla_policies", sa.Column(column, JSONB(), nullable=False, server_default="[]"))
    op.add_column("sla_policies", sa.Column(
        "response_met_on", sa.String(32), nullable=False, server_default="first_reply"))
    op.add_column("sla_policies", sa.Column(
        "resolution_met_on", sa.String(32), nullable=False, server_default="done"))


def downgrade() -> None:
    for column in (*_LISTS, "response_met_on", "resolution_met_on"):
        op.drop_column("sla_policies", column)
