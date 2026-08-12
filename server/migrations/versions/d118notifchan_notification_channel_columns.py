"""per-row notification channel columns (spec 118)

Revision ID: d118notifchan
Revises: d118notifrules

`notifications.inbox` + `notifications.email` — the channel verdict, stamped
when the row is written instead of re-derived on every mailer tick.

**Why it has to be on the row.** RADD-686 filtered each candidate in Python
against its recipient's `email_types`, and that was the only question a row could
answer: by the time the mailer saw it, all it remembered was its TYPE. Spec 118's
answer depends on the RELATION that produced it — assigned to you, watching it,
subscribed to its project — which the fan-out knows and the row did not. So the
decision moves to the write, and both email loops read a column.

**The backfill is `inbox = true, email = false`, deliberately.** Every existing
row IS an inbox row (a muted type never became one), so that half is exact. The
`email` half is not the recipient's real preference and does not try to be:
resolving each historical row's verdict would need the relation that produced it,
which is precisely what was never recorded. What it costs is bounded and small —
a row is only eligible for the immediate mailer while it is unread, unemailed and
under `notify_email_max_age_hours` (24h), so at most one day's un-actioned
notifications go to the DIGEST instead of arriving individually. Nothing is lost;
some of it arrives batched. Guessing `email` from a frozen default set would have
mailed people about types they had turned off, which is the worse error.

The index gains `inbox`: `ix_notifications_user_read` is the unread badge, every
badge poll in every open tab runs it, and the badge now counts inbox rows only.

(Alembic's usual false-positive drops — the runtime-managed pgvector embedding
tables and the example plugin's table — stripped; see PLAN §11.)
"""
from alembic import op
import sqlalchemy as sa

revision = 'd118notifchan'
down_revision = 'd118notifrules'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'notifications',
        sa.Column('inbox', sa.Boolean(), nullable=False, server_default=sa.text('true')),
    )
    op.add_column(
        'notifications',
        sa.Column('email', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    )
    # The server defaults STAY, unlike `d686emailtypes`' — these are not a copy
    # of a policy that lives in code, they are the neutral value for a row
    # inserted by anything that does not know about channels yet, and the ORM
    # writes both columns explicitly on every real path.
    op.drop_index('ix_notifications_user_read', table_name='notifications')
    op.create_index(
        'ix_notifications_user_read', 'notifications', ['user_id', 'read_at', 'inbox']
    )


def downgrade() -> None:
    op.drop_index('ix_notifications_user_read', table_name='notifications')
    op.create_index('ix_notifications_user_read', 'notifications', ['user_id', 'read_at'])
    op.drop_column('notifications', 'email')
    op.drop_column('notifications', 'inbox')
