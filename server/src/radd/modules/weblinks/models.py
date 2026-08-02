import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class ItemWebLink(Base, TimestampMixin):
    """An external/related URL link (docs, design files, references) attached to a work item."""

    __tablename__ = "item_web_links"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), index=True
    )
    url: Mapped[str] = mapped_column(String(2000))
    title: Mapped[str] = mapped_column(String(300), default="")
    category: Mapped[str] = mapped_column(String(20), default="external")  # WebLinkCategory
    # User who added the link; None for system/anonymous actions. Plain UUID (no FK) —
    # weblinks stays module-agnostic and must not depend on auth being enabled.
    created_by: Mapped[uuid.UUID | None]
