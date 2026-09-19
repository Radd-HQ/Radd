"""GitHub hosts and their repositories as rows (RADD-1129).

Same shape as the Forgejo connector (spec 111): connections are rows so a
credential rotates in the UI without a redeploy, and a repository row carries
the DEFAULT project its releases create versions in. The token is stored as-is
because it must be replayable to sign every API request; reads expose
`has_token` / `has_secret`, never the values.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint, true
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin

from .types import GITHUB_COM, GITHUB_COM_API


class GithubConnection(Base, TimestampMixin):
    """One GitHub host Radd talks to — github.com, or a GitHub Enterprise Server."""

    __tablename__ = "github_connections"
    __table_args__ = (UniqueConstraint("name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    #: The WEB base: https://github.com, or https://ghe.example.com. The API base
    #: is derived (api.github.com, or <host>/api/v3) so an admin enters one URL.
    base_url: Mapped[str] = mapped_column(String(500), default=GITHUB_COM)
    #: Read-only API token (fine-grained: Contents + Pull requests read). Only the
    #: backfill and the connection test need it; webhooks work with it empty.
    api_token: Mapped[str] = mapped_column(String(500), default="")
    #: The secret GitHub signs webhook bodies with (X-Hub-Signature-256).
    webhook_secret: Mapped[str] = mapped_column(String(200), default="")
    active: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
    verify_ssl: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)

    @property
    def api_url(self) -> str:
        web = (self.base_url or GITHUB_COM).rstrip("/")
        return GITHUB_COM_API if web == GITHUB_COM else f"{web}/api/v3"


class GithubRepo(Base, TimestampMixin):
    """A repository on a connection, and the project its releases belong to.

    `project_id` is the DEFAULT project — the one a published release creates a
    version in (spec 112). It is deliberately NOT a filter on linking: project
    keys are unique instance-wide, so `RADD-412` in any repository resolves to
    the same item.
    """

    __tablename__ = "github_repos"
    __table_args__ = (UniqueConstraint("connection_id", "full_name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("github_connections.id", ondelete="CASCADE"), index=True
    )
    full_name: Mapped[str] = mapped_column(String(300))  # owner/repo, as GitHub names it
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), index=True, default=None
    )
    default_branch: Mapped[str] = mapped_column(String(200), default="main")
    last_backfill_at: Mapped[datetime | None] = mapped_column(default=None)
    # RADD-1258: the work category a worklog mirrored from this repository's
    # merge/pull requests carries. NULL = the instance's `Development`.
    time_category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("work_categories.id", ondelete="SET NULL"), default=None
    )
