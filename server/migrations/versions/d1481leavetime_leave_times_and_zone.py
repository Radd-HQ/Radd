"""Leave with hours (RADD-1481): boundary times and the zone they are read in.

`leave_periods` gains `start_time`/`end_time` (TIME, NULL = the whole day at that
end) and `timezone` (IANA name; "" on the rows that predate this, read as UTC).
The ordering check now admits a same-day span whose times are ordered, and a new
check keeps team holidays all-day — a holiday is a calendar day, which is what the
NON_WORKING_DAYS socket hands out.

Revision ID: d1481leavetime
Revises: d1446secrets
"""

import sqlalchemy as sa
from alembic import op

revision = "d1481leavetime"
down_revision = "d1446secrets"
branch_labels = None
depends_on = None

DATES_ORDERED = (
    "start_date < end_date OR (start_date = end_date AND "
    "(start_time IS NULL OR end_time IS NULL OR start_time < end_time))"
)
HOLIDAY_ALL_DAY = "team_id IS NULL OR (start_time IS NULL AND end_time IS NULL)"


def upgrade() -> None:
    op.add_column("leave_periods", sa.Column("start_time", sa.Time(), nullable=True))
    op.add_column("leave_periods", sa.Column("end_time", sa.Time(), nullable=True))
    op.add_column(
        "leave_periods",
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default=""),
    )
    op.drop_constraint(op.f("ck_leave_periods_ck_leave_dates_ordered"), "leave_periods", type_="check")
    op.create_check_constraint("ck_leave_dates_ordered", "leave_periods", DATES_ORDERED)
    op.create_check_constraint("ck_leave_holiday_all_day", "leave_periods", HOLIDAY_ALL_DAY)


def downgrade() -> None:
    op.drop_constraint(op.f("ck_leave_periods_ck_leave_holiday_all_day"), "leave_periods", type_="check")
    op.drop_constraint(op.f("ck_leave_periods_ck_leave_dates_ordered"), "leave_periods", type_="check")
    op.create_check_constraint("ck_leave_dates_ordered", "leave_periods", "start_date <= end_date")
    op.drop_column("leave_periods", "timezone")
    op.drop_column("leave_periods", "end_time")
    op.drop_column("leave_periods", "start_time")
