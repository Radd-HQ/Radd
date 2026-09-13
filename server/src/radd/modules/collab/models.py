import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, LargeBinary, func
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base


class PageCollabDoc(Base):
    """The encoded Yjs state of a page's live document (spec 122).

    One row per page, written debounced while a room is open and when its last
    client leaves. `page_version` is the `pages.version` the state corresponds
    to: a room opening with a row whose version matches the page's RESUMES it;
    any other row is discarded, because the page was written by something that
    was not this room and the markdown is the truth.
    """

    __tablename__ = "page_collab_docs"

    page_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pages.id", ondelete="CASCADE"), primary_key=True
    )
    state: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    page_version: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
