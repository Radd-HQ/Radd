"""The columns every connector's connection and repository tables share (RADD-1435).
Each connector keeps its own tables (`forgejo_connections`, `github_repos`, …) and
declares them from these mixins; a connector-only column goes on its own class.
Not named `models.py`: another module may import it (tests/test_module_contracts.py)."""

import uuid
from datetime import datetime
from typing import ClassVar

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from radd.db import TimestampMixin


class ConnectionColumns(TimestampMixin):
    """One host a connector talks to. Credentials are stored as-is (replayed on
    every call); reads expose only has_token/has_secret."""

    @declared_attr.directive
    def __table_args__(cls) -> tuple:
        return (UniqueConstraint("name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    #: The WEB base the admin enters; the connector derives its API base from it.
    base_url: Mapped[str] = mapped_column(String(500))
    #: Read-only API token. The backfill, the connection test and time mirroring
    #: need it; a host that only sends webhooks works with it empty.
    api_token: Mapped[str] = mapped_column(String(500), default="")
    #: What the host signs deliveries with (Forgejo, GitHub) or echoes back (GitLab).
    webhook_secret: Mapped[str] = mapped_column(String(200), default="")
    active: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
    verify_ssl: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)

    @property
    def api_url(self) -> str:
        """The host's REST base, derived from `base_url` — each connector says how."""
        raise NotImplementedError

    @property
    def api_headers(self) -> dict[str, str]:
        """The headers every API call carries, the token included when set."""
        raise NotImplementedError


class RepoColumns(TimestampMixin):
    """A repository on a connection, and the project its releases belong to.

    `project_id` is the DEFAULT project — the one a published release creates a
    version in. With `link_all_projects` off it also bounds issue linking and
    mirrored time; otherwise issue keys link across projects.
    """

    #: The connector's connection table, which `connection_id` references.
    __connection_table__: ClassVar[str]

    @declared_attr.directive
    def __table_args__(cls) -> tuple:
        return (UniqueConstraint("connection_id", "full_name"),)

    @declared_attr
    def connection_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(ForeignKey(f"{cls.__connection_table__}.id", ondelete="CASCADE"), index=True)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    #: The path the host's payloads name: `owner/repo`, or GitLab's `path_with_namespace`.
    full_name: Mapped[str] = mapped_column(String(300))
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), index=True, default=None
    )
    default_branch: Mapped[str] = mapped_column(String(200), default="main")
    last_backfill_at: Mapped[datetime | None] = mapped_column(default=None)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    link_all_projects: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    # RADD-1258: the work category a mirrored worklog carries; NULL = `Development`.
    time_category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("work_categories.id", ondelete="SET NULL"), default=None
    )
    # What a delivery DOES beyond linking and firing triggers — each OFF until
    # someone switches it on: copy time logged on merge/pull requests into
    # worklogs (RADD-1321); move the issues a merged change names to their
    # waiting state, and publish a released version into the default project
    # (RADD-1369, `policies.py`).
    mirror_time: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    move_on_merge: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    publish_on_release: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
