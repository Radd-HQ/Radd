import uuid

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class Project(Base, TimestampMixin):
    __tablename__ = "projects"
    # Key is globally unique (Jira model): `TD-1234` addresses an issue instance-wide
    # (spec 21). Two projects can't both own "TD" — an accepted trade-off for
    # unambiguous issue keys (see PLAN.md).
    __table_args__ = (UniqueConstraint("key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(200))
    # Counter backing per-project item numbers (TD-1, TD-2, …); see allocate_item_number().
    next_number: Mapped[int] = mapped_column(default=1)
