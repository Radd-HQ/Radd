"""RADD-1043 — an SLA policy can filter on issue TYPE, not only priority.

A desk answers a Bug and a Change Request on different promises, and priority is
the wrong axis for that: a normal-priority outage and a normal-priority request
are the same tier. `issue_type_ids` mirrors `priorities` exactly — a JSONB list
that is EMPTY for "every type", so every existing policy keeps matching what it
matched before, and first-match ordering is untouched.

Ids rather than names (a type is a per-project row that can be renamed) and no
foreign key, because JSONB cannot carry one: a type that is deleted simply stops
matching, which narrows the policy rather than erroring.

Revision ID: d1043slatype
Revises: d117pkg
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "d1043slatype"
down_revision = "d117pkg"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sla_policies",
        sa.Column("issue_type_ids", JSONB(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("sla_policies", "issue_type_ids")
