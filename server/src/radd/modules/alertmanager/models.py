import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base


class AlertItem(Base):
    """Alert fingerprint → item dedup map (spec 47): one item per Alertmanager
    fingerprint; repeat notifications become comments on the mapped item."""

    __tablename__ = "alert_items"

    fingerprint: Mapped[str] = mapped_column(Text, primary_key=True)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work_items.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
