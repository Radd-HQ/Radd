"""RADD-1396: queue views are the slas plugin's `slas.queue`; the dead `sla` screen row goes.

Two stored vocabularies the host owned while the SLA feature lived there:

* `views.view_type = 'queue'` — the spec-64 triage queue was a builtin view type
  the host drew with SLA ordering hardwired. It is now a view type the slas plugin
  contributes (`ViewTypeSpec`, drawn by the host's list over the plugin's rows),
  and a contributed key is namespaced by its plugin, as `slas.timer` was in
  RADD-1394. Rewritten in place; downgrade restores `queue`.
* `screen_fields.field = 'sla'` — the screens editor's "SLA timers" row. Since
  RADD-1394 the SLA card is the slas plugin's issue-rail contribution, which no
  screen placement reached, so the row arranged nothing. The builtin is deleted
  and its stored rows with it; downgrade cannot tell which screens had one, and
  the row placed nothing anyway, so it does not recreate them.

Revision ID: d1396slaqueue
Revises: d1394slacols
"""

import sqlalchemy as sa
from alembic import op

revision = "d1396slaqueue"
down_revision = "d1394slacols"
branch_labels = None
depends_on = None

OLD_QUEUE = "queue"
NEW_QUEUE = "slas.queue"
SLA_SCREEN_ROW = "sla"


def _retype(old: str, new: str) -> None:
    op.get_bind().execute(
        sa.text("UPDATE views SET view_type = :new WHERE view_type = :old"),
        {"old": old, "new": new},
    )


def upgrade() -> None:
    _retype(OLD_QUEUE, NEW_QUEUE)
    op.get_bind().execute(
        sa.text("DELETE FROM screen_fields WHERE field = :field"), {"field": SLA_SCREEN_ROW}
    )


def downgrade() -> None:
    _retype(NEW_QUEUE, OLD_QUEUE)
