import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class WebhookEndpoint(Base, TimestampMixin):
    __tablename__ = "webhook_endpoints"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    url: Mapped[str] = mapped_column(String(1000))
    # Needed for signing, so stored as-is; encrypt at rest when the secrets layer lands.
    secret: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(500), default="")
    # None = all events; otherwise exact event-type strings.
    event_types: Mapped[list[str] | None] = mapped_column(JSONB)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class WebhookDelivery(Base, TimestampMixin):
    __tablename__ = "webhook_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    endpoint_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("webhook_endpoints.id"), index=True)
    event_id: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(10), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(index=True)
    last_status_code: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(String(500))
