import uuid

from sqlalchemy import Boolean, String, Text, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin

from ..types import ConfluenceAuthMode, ConnectionSource


class ConfluenceConnection(Base, TimestampMixin):
    """One Confluence instance to import from. The credential is replayed per
    request, so it is stored recoverably — as secretbox ciphertext (RADD-1424;
    `connections.creds_of` decrypts, legacy plaintext is encrypted on the row's next
    save or boot) — and never returned (`has_credential`)."""

    __tablename__ = "confluence_connections"
    __table_args__ = (UniqueConstraint("name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    base_url: Mapped[str] = mapped_column(String(500))
    auth_mode: Mapped[str] = mapped_column(String(20), default=ConfluenceAuthMode.PAT.value)
    username: Mapped[str] = mapped_column(String(200), default="")  # basic auth only
    credential: Mapped[str] = mapped_column(Text, default="")  # PAT or password, sealed
    # Internal CAs and self-signed certs are the norm on a self-hosted DC instance.
    verify_ssl: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    source: Mapped[str] = mapped_column(String(20), default=ConnectionSource.USER.value)

    @property
    def has_credential(self) -> bool:
        """What the API exposes in place of the credential itself."""
        return bool(self.credential)

    @property
    def external_source(self) -> str:
        """The `pages.external_source` value for rows this connection imports.

        The INSTANCE, not the product: two Confluence servers both have a page
        `12345`, so qualifying by host is what keeps their identities apart. Derived
        rather than stored, so it cannot drift from the URL it describes.
        """
        host = self.base_url.split("://", 1)[-1].split("/", 1)[0]
        return f"confluence:{host}"
