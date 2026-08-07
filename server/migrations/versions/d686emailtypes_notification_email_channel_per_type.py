"""notification email channel per type (RADD-686)

Revision ID: d686emailtypes
Revises: d958mailcfg

Adds `notification_prefs.email_types` — the second column of the per-type
channel matrix (inbox = not in `muted_types`, email = in `email_types`).

**Existing rows get the defaults, not an empty list.** Everyone who had ever
saved a preference already had comment mail (RADD-968's `{commented}` constant);
handing them `[]` would silence a channel they never asked to turn off. The
ADD COLUMN carries a server_default, which is what fills those rows in place
(Postgres 11+ does it without a table rewrite), and the default is then DROPPED:
the policy lives in `notify.types.DEFAULT_EMAIL_TYPES`, and a copy of it left
sitting in the schema is a second source of truth that silently goes stale.

The literal below is a FROZEN SNAPSHOT of that constant as of this revision, not
an import of it. A migration must keep meaning what it meant the day it ran —
importing the live constant would rewrite history every time the default set is
edited.

(Alembic's usual false-positive drops — the runtime-managed pgvector embedding
tables, the example plugin's table, and the doc_→page_ index renames — stripped;
see PLAN §11.)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'd686emailtypes'
down_revision = 'd958mailcfg'
branch_labels = None
depends_on = None

# notify.types.DEFAULT_EMAIL_TYPES at this revision, in declaration order.
_DEFAULT_EMAIL_TYPES = '["assigned", "mentioned", "commented", "approval"]'


def upgrade() -> None:
    op.add_column(
        'notification_prefs',
        sa.Column(
            'email_types',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text(f"'{_DEFAULT_EMAIL_TYPES}'::jsonb"),
        ),
    )
    op.alter_column('notification_prefs', 'email_types', server_default=None)


def downgrade() -> None:
    op.drop_column('notification_prefs', 'email_types')
