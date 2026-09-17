import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class AccessGrant(Base, TimestampMixin):
    """One access grant (spec 92): a SUBJECT (user|team|role) is granted an ACCESS
    (read|write|…) on a RESOURCE (resource_type + resource_id), SCOPED to a project
    (NULL = every scope the resource applies in) — the single, generic ACL row used
    by fields, builtin fields, views, and any plugin-registered resource.

    `resource_id` is a string so it can hold a uuid (a field/view id) OR a stable
    key (a builtin field name). No FK on it (polymorphic) — a resource deletes its
    grants via `service.clear_resource`. `subject_id` is polymorphic too (validated
    against the subject's table in the service).
    """

    __tablename__ = "access_grants"
    __table_args__ = (
        UniqueConstraint(
            "resource_type", "resource_id", "subject_type", "subject_id", "access", "project_id",
            name="uq_access_grants_row",
        ),
        Index("ix_access_grants_resource", "resource_type", "resource_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    resource_type: Mapped[str] = mapped_column(String(40))
    resource_id: Mapped[str] = mapped_column(String(100))
    subject_type: Mapped[str] = mapped_column(String(10))  # GrantSubject
    subject_id: Mapped[uuid.UUID] = mapped_column(index=True)
    access: Mapped[str] = mapped_column(String(20))  # Access (resource-declared)
    # RADD-819: allow (default) | deny. Deny wins at equal scope; the NARROWER
    # scope wins across scopes (a project deny beats a global allow AND a
    # project allow beats a global deny — specificity first, deny on ties).
    effect: Mapped[str] = mapped_column(String(5), default="allow", server_default="allow")
    # RADD-820: NULL = permanent (every pre-existing row). Applied at
    # RESOLUTION time — an expired grant is absent the moment it passes, and
    # the sweep merely deletes corpses. `granted_by` NULL = pre-existing or
    # system-created, which is honest: nobody knows who granted those.
    expires_at: Mapped["datetime | None"] = mapped_column(nullable=True)
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # NULL = every project (global); set = that project only. Widen by adding rows.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )


class AccessRestriction(Base):
    """Explicit closed mode survives the expiry/removal of individual allows."""
    __tablename__ = "access_restrictions"
    __table_args__ = (UniqueConstraint("resource_type", "resource_id", "access", "project_id",
        name="uq_access_restriction_scope", postgresql_nulls_not_distinct=True),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    resource_type: Mapped[str] = mapped_column(String(40))
    resource_id: Mapped[str] = mapped_column(String(100))
    access: Mapped[str] = mapped_column(String(20))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
