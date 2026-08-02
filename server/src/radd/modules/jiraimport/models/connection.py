import uuid

from sqlalchemy import Boolean, String, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin

from ..types import JiraAuthMode, JiraConnectionSource


class JiraConnection(Base, TimestampMixin):
    """One Jira instance Radd can import from (spec 100).

    Connections moved out of the environment and into the database because the
    env-only design could point at exactly one instance and needed a redeploy to
    change — including to fix a typo in the URL. Snapshots record which connection
    produced them, so an import always knows where its data came from.

    The credential is stored as-is: a PAT must be replayable to sign every request,
    so it cannot be hashed. That matches the existing precedent for webhook signing
    secrets (`webhooks/models.py`) and carries the same caveat — encrypt at rest
    when the secrets layer lands. It is never returned over the API; reads expose
    `has_credential` instead.
    """

    __tablename__ = "jira_connections"
    __table_args__ = (UniqueConstraint("name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    base_url: Mapped[str] = mapped_column(String(500))
    auth_mode: Mapped[str] = mapped_column(String(20), default=JiraAuthMode.PAT.value)
    username: Mapped[str] = mapped_column(String(200), default="")  # basic auth only
    credential: Mapped[str] = mapped_column(String(500), default="")  # PAT or password
    # Internal CAs and self-signed certs are the norm on a self-hosted DC instance.
    verify_ssl: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
    # Exactly one row is the default; the service keeps that invariant.
    is_default: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    source: Mapped[str] = mapped_column(String(20), default=JiraConnectionSource.USER.value)

    @property
    def has_credential(self) -> bool:
        """What the API exposes in place of the credential itself."""
        return bool(self.credential)
