import uuid

from sqlalchemy import Boolean, String, Text, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin

from ..types import JiraAuthMode, JiraConnectionSource


class JiraConnection(Base, TimestampMixin):
    """One Jira instance to import from. The credential is replayed per request, so it
    is stored recoverably — as secretbox ciphertext (RADD-1424; `connections.creds_of`
    decrypts, legacy plaintext is encrypted on the row's next save or boot) — and
    never returned (reads expose `has_credential`)."""

    __tablename__ = "jira_connections"
    __table_args__ = (UniqueConstraint("name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    base_url: Mapped[str] = mapped_column(String(500))
    auth_mode: Mapped[str] = mapped_column(String(20), default=JiraAuthMode.PAT.value)
    username: Mapped[str] = mapped_column(String(200), default="")  # basic auth only
    credential: Mapped[str] = mapped_column(Text, default="")  # PAT or password, sealed
    # Internal CAs and self-signed certs are the norm on a self-hosted DC instance.
    verify_ssl: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
    # Exactly one row is the default; the service keeps that invariant.
    is_default: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    source: Mapped[str] = mapped_column(String(20), default=JiraConnectionSource.USER.value)

    @property
    def has_credential(self) -> bool:
        """What the API exposes in place of the credential itself."""
        return bool(self.credential)
