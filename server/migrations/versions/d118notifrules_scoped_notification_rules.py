"""scoped notification rules (spec 118)

Revision ID: d118notifrules
Revises: 6fac157b10ac

`notification_rules` replaces `notification_prefs.muted_types` +
`email_types` — one answer per (person, scope, kind) instead of one answer per
(person, kind) for the whole instance.

**Every stored preference is carried across, into `own` and `participating`
only.** RADD-686's matrix had no notion of relation, so a saved preference means
exactly the same thing in both columns and nothing at all in the third. Writing
it into `teams` as well would subscribe every existing user to their whole
team's traffic on the strength of a checkbox they ticked about their own issues
— a behaviour change dressed up as a data migration. The my-teams column starts
empty and OFF, which is what those users have today.

A muted type becomes `off`; a type in `email_types` becomes `both`; anything
else becomes `inbox`. That is the RADD-686 semantics stated as cells: email
REQUIRED inbox back then (a muted type never became a row, and the mailer mailed
rows), so `email` with no inbox is unreachable from the old data and only
appears once someone chooses it.

**What this migration preserves is the CHANNELS, not the audience.** Every person
the old fan-out reached keeps receiving exactly what they received; nothing here
touches WHO an event reaches, and spec 118 deliberately widens that separately —
`own` (assignee or reporter) joins the ambient audience whether or not they
watch, so an assignee who had unwatched, and every assignee/reporter on an
IMPORTED item (a silent import writes no auto-watch rows), starts receiving
ambient notifications and the `commented` mail that goes with them. That is the
requested behaviour of the `own` column, and the column is its off switch; it is
recorded here because a data migration is where someone will later come looking
for the reason their mail volume changed.

The kind list below is a FROZEN SNAPSHOT of `notify.kinds.NOTIFICATION_KINDS` as
of this revision, not an import of it — the same rule `d686emailtypes` recorded.
A migration must keep meaning what it meant the day it ran, and importing the
live vocabulary would rewrite history every time a kind is added. The three
kinds spec 118 introduced (`created`, `updated`, `page_created`) are deliberately
absent from the backfill: a migrated row says nothing about them, so they fall
through to their `off` default like everyone else's.

Two PARTIAL unique indexes rather than one constraint: relationship rows carry
`scope_id IS NULL`, and Postgres counts NULLs as distinct, so a plain UNIQUE
(user_id, scope, scope_id) would let a person hold two `own` rules and leave the
resolver picking whichever it indexed last.

(Alembic's usual false-positive drops — the runtime-managed pgvector embedding
tables and the example plugin's table — stripped; see PLAN §11.)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'd118notifrules'
down_revision = '6fac157b10ac'
branch_labels = None
depends_on = None

# notify.kinds.NOTIFICATION_KINDS' pre-existing members at this revision — the
# ten types RADD-686's two lists could talk about.
_MIGRATED_KINDS = (
    "assigned",
    "mentioned",
    "participant_added",
    "approval",
    "automation",
    "commented",
    "state_changed",
    "sla_breach",
    "sla_due_soon",
    "page_updated",
)

# The two relationship columns a stored RADD-686 preference means (see above).
_CARRIED_SCOPES = ("own", "participating")

#: One row per (prefs row × carried scope), with `channels` built in SQL from the
#: two JSONB lists. jsonb_object_agg over a literal kind list keeps the whole
#: backfill in one statement — a Python loop here would need the app's session,
#: which a migration does not have.
_BACKFILL = """
INSERT INTO notification_rules (id, user_id, scope, scope_id, channels, updated_at)
SELECT
    gen_random_uuid(),
    p.user_id,
    s.scope,
    NULL,
    (
        SELECT jsonb_object_agg(
            k.kind,
            CASE
                WHEN p.muted_types ? k.kind THEN 'off'
                WHEN p.email_types ? k.kind THEN 'both'
                ELSE 'inbox'
            END
        )
        FROM unnest(%(kinds)s::text[]) AS k(kind)
    ),
    now()
FROM notification_prefs p
CROSS JOIN unnest(%(scopes)s::text[]) AS s(scope)
"""


def upgrade() -> None:
    op.create_table(
        'notification_rules',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('scope', sa.String(length=20), nullable=False),
        sa.Column('scope_id', sa.Uuid(), nullable=True),
        sa.Column(
            'channels', postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            'updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_notification_rules_user_id'), 'notification_rules', ['user_id']
    )
    op.create_index(
        'ix_notification_rules_target', 'notification_rules', ['scope', 'scope_id']
    )
    op.create_index(
        'uq_notification_rules_subscription',
        'notification_rules',
        ['user_id', 'scope', 'scope_id'],
        unique=True,
        postgresql_where=sa.text('scope_id IS NOT NULL'),
    )
    op.create_index(
        'uq_notification_rules_relationship',
        'notification_rules',
        ['user_id', 'scope'],
        unique=True,
        postgresql_where=sa.text('scope_id IS NULL'),
    )

    op.execute(
        sa.text(
            _BACKFILL
            % {
                "kinds": "'{%s}'" % ",".join(_MIGRATED_KINDS),
                "scopes": "'{%s}'" % ",".join(_CARRIED_SCOPES),
            }
        )
    )

    op.drop_column('notification_prefs', 'muted_types')
    op.drop_column('notification_prefs', 'email_types')


def downgrade() -> None:
    op.add_column(
        'notification_prefs',
        sa.Column(
            'email_types',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        'notification_prefs',
        sa.Column(
            'muted_types',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.drop_index('uq_notification_rules_relationship', table_name='notification_rules')
    op.drop_index('uq_notification_rules_subscription', table_name='notification_rules')
    op.drop_index('ix_notification_rules_target', table_name='notification_rules')
    op.drop_index(op.f('ix_notification_rules_user_id'), table_name='notification_rules')
    op.drop_table('notification_rules')
