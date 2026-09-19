"""GitLab hosts and their projects as rows (RADD-1253).

Spec 31 configured this connector with a single environment secret, which could
name exactly one host and needed a redeploy to rotate — and gave the connector
no API token at all, so nothing could ever be read back (no backfill, no time
entries). Same shape as the Forgejo (spec 111) and GitHub (RADD-1129)
connectors: rows, with the env key demoted to a one-time seed. The token is
stored as-is because it must be replayable to sign every request; reads expose
`has_token` / `has_secret`, never the values.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint, true
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin

from .types import GITLAB_COM


class GitlabConnection(Base, TimestampMixin):
    """One GitLab host Radd talks to — gitlab.com, or a self-managed instance."""

    __tablename__ = "gitlab_connections"
    __table_args__ = (UniqueConstraint("name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    #: The WEB base: https://gitlab.com or https://gitlab.example.com. REST and
    #: GraphQL bases are derived, so an admin enters one URL.
    base_url: Mapped[str] = mapped_column(String(500), default=GITLAB_COM)
    #: Personal/project/group access token with `read_api`. The backfill, the
    #: connection test and the timelog fetch need it; webhooks work with it
    #: empty. An ADMIN's token also exposes other users' emails, which is what
    #: makes worklog author matching automatic on an LDAP-backed host.
    api_token: Mapped[str] = mapped_column(String(500), default="")
    #: The "Secret token" entered on the hook; GitLab sends it back verbatim as
    #: `X-Gitlab-Token` (no HMAC).
    webhook_secret: Mapped[str] = mapped_column(String(200), default="")
    active: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
    verify_ssl: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)

    @property
    def api_url(self) -> str:
        return f"{(self.base_url or GITLAB_COM).rstrip('/')}/api/v4"

    @property
    def graphql_url(self) -> str:
        return f"{(self.base_url or GITLAB_COM).rstrip('/')}/api/graphql"


class GitlabRepo(Base, TimestampMixin):
    """A project on a connection, and the Radd project its releases belong to.

    `full_name` is GitLab's `path_with_namespace` (`group/subgroup/project`) —
    named like the other connectors' column so the settings page shares one wire
    shape. `project_id` is the DEFAULT project — the one a release trigger
    creates a version in (spec 112). It is deliberately NOT a filter on linking:
    project keys are unique instance-wide.
    """

    __tablename__ = "gitlab_repos"
    __table_args__ = (UniqueConstraint("connection_id", "full_name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gitlab_connections.id", ondelete="CASCADE"), index=True
    )
    full_name: Mapped[str] = mapped_column(String(300))
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), index=True, default=None
    )
    default_branch: Mapped[str] = mapped_column(String(200), default="main")
    last_backfill_at: Mapped[datetime | None] = mapped_column(default=None)
    # RADD-1258: the work category a worklog mirrored from this project's merge
    # requests carries. NULL = the instance's `Development`.
    time_category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("work_categories.id", ondelete="SET NULL"), default=None
    )
