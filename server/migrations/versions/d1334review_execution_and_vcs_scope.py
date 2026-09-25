"""Fail-closed automation owners and connection-scoped VCS ingestion."""

import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d1334review"
down_revision = "d1333review"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("fk_automations_created_by_id_users", "automations", type_="foreignkey")
    connection = op.get_bind()
    users = dict(connection.execute(sa.text("SELECT email, id FROM users")).all())
    for row in connection.execute(sa.text("SELECT id, nodes FROM automations")).mappings().all():
        changed = False
        for node in row["nodes"] or []:
            params = node.get("params") or {}
            if params.get("act_as") and not params.get("act_as_id"):
                params["act_as_id"] = str(users.get(params["act_as"]) or uuid.uuid4())
                changed = True
        if changed:
            connection.execute(
                sa.text("UPDATE automations SET nodes = :nodes WHERE id = :id").bindparams(
                    sa.bindparam("nodes", type_=postgresql.JSONB())
                ),
                {"nodes": row["nodes"], "id": row["id"]},
            )
    op.create_table("vcs_seeds", sa.Column("provider", sa.String(20), primary_key=True))
    for host in ("github", "gitlab", "forgejo"):
        op.add_column(
            f"{host}_repos",
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        )
        op.add_column(
            f"{host}_repos",
            sa.Column("link_all_projects", sa.Boolean(), nullable=False, server_default=sa.true()),
        )
        op.execute(
            sa.text(
                f"INSERT INTO vcs_seeds(provider) SELECT '{host}' WHERE EXISTS (SELECT 1 FROM {host}_connections)"
            )
        )
    op.add_column("item_vcs_links", sa.Column("connection_id", sa.Uuid(), nullable=True))
    op.add_column(
        "item_vcs_links",
        sa.Column("ci_reports", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "item_vcs_links",
        sa.Column("ci_head_sha", sa.String(100), nullable=False, server_default=""),
    )
    op.add_column("item_vcs_links", sa.Column("ci_head_started_at", sa.DateTime(), nullable=True))
    op.create_index("ix_item_vcs_links_connection_id", "item_vcs_links", ["connection_id"])
    op.drop_index("uq_item_vcs_links_ref", table_name="item_vcs_links")
    # Preserve unambiguous existing associations. Unknown origins stay historical
    # and are not changed by any connection until re-linked/backfilled.
    for host in ("github", "gitlab", "forgejo"):
        op.execute(
            sa.text(f"""
            UPDATE item_vcs_links AS link SET connection_id = candidates.connection_id
            FROM (SELECT l.id, (array_agg(c.id))[1] AS connection_id
                  FROM item_vcs_links l JOIN {host}_connections c
                    ON l.url LIKE rtrim(c.base_url, '/') || '/%'
                  WHERE l.provider = '{host}' GROUP BY l.id HAVING count(*) = 1) candidates
            WHERE link.id = candidates.id
        """)
        )
    op.create_index(
        "uq_item_vcs_links_ref",
        "item_vcs_links",
        ["item_id", "provider", "connection_id", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id <> '' AND connection_id IS NOT NULL"),
    )
    op.create_index(
        "uq_item_vcs_links_legacy_ref",
        "item_vcs_links",
        ["item_id", "provider", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id <> '' AND connection_id IS NULL"),
    )
    for table in ("vcs_pending_worklogs", "worklogs"):
        for column in ("external_id", "external_scope"):
            op.alter_column(table, column, type_=sa.String(512), existing_type=sa.String(200))
    op.execute(
        sa.text(
            "UPDATE vcs_pending_worklogs SET external_id = connection_id::text || ':' || external_id, external_scope = connection_id::text || ':' || external_scope"
        )
    )
    # Existing mirrored worklogs lack a connection column. Attribute only rows
    # whose provider had exactly one host; ambiguous rows remain historical.
    for host in ("github", "gitlab", "forgejo"):
        op.execute(
            sa.text(f"""WITH origin AS (
                SELECT (array_agg(id))[1]::text AS id FROM {host}_connections HAVING count(*) = 1)
            UPDATE worklogs SET external_id = origin.id || ':' || external_id,
                external_scope = origin.id || ':' || external_scope
            FROM origin WHERE external_source = '{host}' AND external_id <> ''""")
        )


def downgrade():
    # Multiple hosts can now legitimately share external IDs. Collapsing them
    # would lose data; retain scoped indexes and require a deliberate export.
    raise RuntimeError("Export connection-scoped VCS data before downgrading this migration")
