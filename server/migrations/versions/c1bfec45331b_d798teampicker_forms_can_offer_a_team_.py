"""d798teampicker: a form can offer the submitter a team picker

RADD-798. Off by default (`server_default false`), because turning it on decides
who else can OPEN the requests filed through that form — an existing form must
not start sharing anything the day this deploys.

Hand-trimmed, like `307a8b156894`: autogenerate again proposed dropping
`item_embeddings`/`page_embeddings` (runtime-managed outside `Base.metadata`,
spec 103), the example plugin's `acme_notes`, and a pile of doc->page index
renames left over from RADD-701. None of that is this change, and letting it ride
would drop the semantic index on deploy.

Revision ID: c1bfec45331b
Revises: 307a8b156894
Create Date: 2026-08-03 23:29:08.588748

"""
from alembic import op
import sqlalchemy as sa

revision = 'c1bfec45331b'
down_revision = '307a8b156894'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'forms',
        sa.Column(
            'team_picker_enabled',
            sa.Boolean(),
            server_default=sa.text('false'),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column('forms', 'team_picker_enabled')
