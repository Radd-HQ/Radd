"""RADD-1314: a key the automation engine mints carries its causation.

A script run (RADD-1269) writes back over REST with an ephemeral key. That
request never entered `events.automated()`, so its events looked human and a
script that updated its own item re-triggered its own automation — hidden until
RADD-1308 stopped treating the system actor as automation-caused. The key now
records the cause, and a request authenticated with it runs as automated.

JSONB rather than a boolean: chaining (RADD-1315) adds the causing rule and the
chain depth to the same object.

Revision ID: d1314autokey
Revises: d1302manager
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d1314autokey"
down_revision = "d1302manager"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("api_tokens", sa.Column("automation_cause", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("api_tokens", "automation_cause")
