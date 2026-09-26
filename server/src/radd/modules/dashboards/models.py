import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class Dashboard(Base, TimestampMixin):
    """A composable dashboard (spec 75): a shareable arrangement of widgets over
    existing read surfaces, fetched through the ordinary APIs at render time so
    RBAC is inherited. `owner_id` = the creator; grants at a ShareLevel;
    `global_access` = what every active user gets (never 'owner' -> 409)."""

    __tablename__ = "dashboards"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    # ShareLevel every active user gets, or NULL = not globally visible
    # (enabling it is gated on dashboard.create — it's a server-wide broadcast).
    global_access: Mapped[str | None] = mapped_column(String(10))
    position: Mapped[int] = mapped_column(Integer, default=0)


class DashboardWidget(Base, TimestampMixin):
    """One widget on a dashboard: a `WidgetType` + its per-type `config`
    (JSONB, validated on write — shape via the discriminated schema union,
    references [project/cycle/view existence + writer visibility, SLQ compile]
    in widgets.py), a grid `width` in twelfths, pixel height, and `position` ordering.
    `title` overrides the card's default label. Rows die with the dashboard
    (FK CASCADE)."""

    __tablename__ = "dashboard_widgets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    dashboard_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dashboards.id", ondelete="CASCADE"), index=True
    )
    widget_type: Mapped[str] = mapped_column(String(30))  # WidgetType
    title: Mapped[str | None] = mapped_column(String(200))
    width: Mapped[int] = mapped_column(Integer, default=4)  # twelve-column grid
    position: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=360, server_default="360")
    collapsed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
