import uuid
from typing import Any

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class Dashboard(Base, TimestampMixin):
    """A composable dashboard (spec 75): a named, shareable arrangement of
    widgets over data surfaces that ALREADY exist (reports, SLQ counts/lists,
    view counts). Ownership + sharing copy the spec-57 view idiom verbatim:
    `owner_id` = the creator (full control — edit, share, delete, transfer),
    `access_grants` grantees at a ShareLevel, `global_access` = what
    every active user gets (NULL = not globally visible; never 'owner'
    → 409). Widgets fetch through the ordinary read APIs at render time, so
    RBAC/visibility filtering is inherited, never reimplemented here."""

    __tablename__ = "dashboards"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    # ShareLevel every active user gets, or NULL = not globally visible
    # (enabling it is gated on dashboard.create — it's a server-wide broadcast).
    global_access: Mapped[str | None] = mapped_column(String(10))
    position: Mapped[int] = mapped_column(Integer, default=0)


# `DashboardShare` is gone (spec 92, adopted): per-subject dashboard
# sharing lives in the generic `access_grants` table under resource_type
# "dashboard", exactly as view sharing does. The table was a verbatim copy of
# `view_shares`, which spec 92 had already deleted — see dashboards/service.py.


class DashboardWidget(Base, TimestampMixin):
    """One widget on a dashboard: a `WidgetType` + its per-type `config`
    (JSONB, validated on write — shape via the discriminated schema union,
    references [project/cycle/view existence + writer visibility, SLQ compile]
    in widgets.py), a grid `width` in thirds (1..3), and `position` ordering.
    `title` overrides the card's default label. Rows die with the dashboard
    (FK CASCADE)."""

    __tablename__ = "dashboard_widgets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    dashboard_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dashboards.id", ondelete="CASCADE"), index=True
    )
    widget_type: Mapped[str] = mapped_column(String(30))  # WidgetType
    title: Mapped[str | None] = mapped_column(String(200))
    width: Mapped[int] = mapped_column(Integer, default=1)  # grid thirds, 1..3
    position: Mapped[int] = mapped_column(Integer, default=0)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
