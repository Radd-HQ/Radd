"""d1560authepoch: an epoch that moves when authorization data changes (RADD-1560)

One row, and a statement trigger on each table an authorization answer is read
from. A change to any of them, by any route (the service layer, a bulk
statement, a cascade from a deleted team, a psql prompt), adds one to the epoch
in the same transaction; `radd/authcache.py` uses cached answers only while the
epoch is unchanged.

The triggers fire BEFORE the statement, so a transaction takes the epoch row
before it touches the rows themselves: two transactions changing grants queue on
the epoch instead of deadlocking on each other's rows. The cost is that
authorization changes are serialised instance-wide for as long as the changing
transaction is open.

Revision ID: d1560authepoch
Revises: d1552countcover
Create Date: 2026-11-17
"""

from alembic import op

revision = "d1560authepoch"
down_revision = "d1552countcover"
branch_labels = None
depends_on = None

#: Must match `radd.authcache.WATCHED_TABLES` (a test compares them).
WATCHED_TABLES = ("global_role_grants", "roles", "team_members", "group_members", "group_parents")


def upgrade():
    op.execute(
        "CREATE TABLE auth_epoch ("
        " id smallint PRIMARY KEY CHECK (id = 1),"
        " value bigint NOT NULL)"
    )
    op.execute("INSERT INTO auth_epoch (id, value) VALUES (1, 1)")
    op.execute(
        """
        CREATE FUNCTION radd_bump_auth_epoch() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            UPDATE auth_epoch SET value = value + 1 WHERE id = 1;
            RETURN NULL;
        END $$
        """
    )
    for table in WATCHED_TABLES:
        op.execute(
            f"CREATE TRIGGER radd_auth_epoch BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE "
            f"ON {table} FOR EACH STATEMENT EXECUTE FUNCTION radd_bump_auth_epoch()"
        )


def downgrade():
    for table in WATCHED_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS radd_auth_epoch ON {table}")
    op.execute("DROP FUNCTION IF EXISTS radd_bump_auth_epoch()")
    op.execute("DROP TABLE IF EXISTS auth_epoch")
