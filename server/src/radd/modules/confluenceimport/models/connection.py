import uuid

from sqlalchemy import Boolean, String, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin

from ..types import ConfluenceAuthMode, ConnectionSource


class ConfluenceConnection(Base, TimestampMixin):
    """One Confluence instance Radd can import from (spec 117).

    The `JiraConnection` shape verbatim, deliberately: copying it means the
    exactly-one-default invariant, the redacted-credential read and the env
    seeding all behave identically across the two importers, and an admin who has
    configured one already knows how the other works. Inventing a second
    connection idiom would buy nothing.

    The credential is stored as-is — a PAT must be replayable to sign every
    request, so it cannot be hashed — matching the webhook-signing-secret
    precedent and carrying the same caveat: encrypt at rest when the secrets layer
    lands. It is never returned over the API; reads expose `has_credential`.
    """

    __tablename__ = "confluence_connections"
    __table_args__ = (UniqueConstraint("name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    base_url: Mapped[str] = mapped_column(String(500))
    auth_mode: Mapped[str] = mapped_column(String(20), default=ConfluenceAuthMode.PAT.value)
    username: Mapped[str] = mapped_column(String(200), default="")  # basic auth only
    credential: Mapped[str] = mapped_column(String(500), default="")  # PAT or password
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
