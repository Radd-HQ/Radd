"""Forgejo/Gitea hosts and their repositories as rows (spec 111).

Spec 47 configured this connector with a single environment secret, which could
name exactly one host and needed a redeploy to rotate. Connections follow the
jiraimport (spec 100) and ai_providers (spec 101) precedent instead: rows, with
the env key demoted to a one-time seed.

The credential is stored as-is for the same reason Jira's is — a token must be
replayable to sign every request, so it cannot be hashed. Reads expose
`has_token` / `has_secret` rather than the values.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint, true
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class ForgejoConnection(Base, TimestampMixin):
    """One Forgejo/Gitea host Radd talks to."""

    __tablename__ = "forgejo_connections"
    __table_args__ = (UniqueConstraint("name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    base_url: Mapped[str] = mapped_column(String(500))  # https://git.example.com
    #: Read-only API token. Only the backfill and CI polling need it; a host that
    #: only pushes webhooks works with this empty.
    api_token: Mapped[str] = mapped_column(String(500), default="")
    #: The shared secret the host signs webhook bodies with (HMAC-SHA256).
    webhook_secret: Mapped[str] = mapped_column(String(200), default="")
    active: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
    verify_ssl: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)


class ForgejoRepo(Base, TimestampMixin):
    """A repository on a connection, and the project its releases belong to.

    `project_id` is the DEFAULT project — the one a release tag creates a version
    in (spec 112) and the one the UI groups under. It is deliberately NOT a filter
    on linking: project keys are unique instance-wide, so `RADD-412` in any
    repository resolves to the same item. Making the map authoritative would mean
    a reference from a shared repository silently failing to link.
    """

    __tablename__ = "forgejo_repos"
    __table_args__ = (UniqueConstraint("connection_id", "full_name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("forgejo_connections.id", ondelete="CASCADE"), index=True
    )
    full_name: Mapped[str] = mapped_column(String(300))  # owner/repo, as the payload names it
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
