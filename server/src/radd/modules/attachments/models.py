"""Attachment storage tables (spec 102).

`storage_hosts` moved storage out of the environment: several S3 deployments
(plus filesystem roots) coexist, and every attachment row names the host its
bytes live on. `storage_rules` is the ordered routing chain deciding the host
per upload; `attachment_move_jobs` tracks background rebalancing. Attachments
themselves became polymorphic — `(entity_type, entity_id)` instead of a hard
item FK — so wiki pages can own files too (no FK: cleanup is the GC consumer's
job, which also finally removes BYTES, not just rows).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin

from .types import (
    AttachmentParentType,
    AttachmentState,
    DeliveryMode,
    MoveJobState,
    StorageHostSource,
)


class StorageHost(Base, TimestampMixin):
    """One place bytes can live: an S3-compatible endpoint+bucket, or a local
    filesystem root. Credentials stored as-is (replayed on every request — the
    webhook-secret precedent); reads expose `has_secret_key`. `updated_at`
    doubles as the per-host client-cache fingerprint."""

    __tablename__ = "storage_hosts"
    __table_args__ = (UniqueConstraint("name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    host_type: Mapped[str] = mapped_column(String(20))  # StorageHostType
    endpoint: Mapped[str] = mapped_column(String(500), default="")  # s3: host:port, no scheme
    access_key: Mapped[str] = mapped_column(String(200), default="")
    secret_key: Mapped[str] = mapped_column(Text, default="")
    bucket: Mapped[str] = mapped_column(String(200), default="")
    region: Mapped[str] = mapped_column(String(100), default="")
    secure: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    root_dir: Mapped[str] = mapped_column(String(500), default="")  # filesystem type only
    # presigned = the browser fetches from the host directly, which is what lets
    # a zoned host's content stay unreachable to users outside its network.
    delivery_mode: Mapped[str] = mapped_column(String(20), default=DeliveryMode.PROXY.value)
    presign_expiry_seconds: Mapped[int | None] = mapped_column(Integer)  # None = global default
    user_selectable: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    is_default: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    source: Mapped[str] = mapped_column(String(10), default=StorageHostSource.USER.value)

    @property
    def has_secret_key(self) -> bool:
        return bool(self.secret_key)


class StorageRule(Base, TimestampMixin):
    """One link in the ordered routing chain (first match wins; no match falls
    through; nothing matches -> the default host). `config` is validated by the
    rule type's pydantic model (spec 102 §routing)."""

    __tablename__ = "storage_rules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    rule_type: Mapped[str] = mapped_column(String(20))  # RuleType
    position: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)


class Attachment(Base):
    """A file attached to a work item or wiki page. Bytes live on the named
    storage host under `storage_name`."""

    __tablename__ = "attachments"
    __table_args__ = (Index("ix_attachments_entity", "entity_type", "entity_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Polymorphic parent — kernel entity vocabulary ("item" | "page"), no FK;
    # the GC consumer removes rows AND bytes when the parent dies.
    entity_type: Mapped[str] = mapped_column(String(50))  # AttachmentParentType
    entity_id: Mapped[uuid.UUID] = mapped_column()
    filename: Mapped[str] = mapped_column(String(300))
    content_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    # Object key on every host type (uuid hex) — never derived from user input.
    storage_name: Mapped[str] = mapped_column(String(64), unique=True)
    storage_host_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("storage_hosts.id", ondelete="RESTRICT"), index=True
    )
    # STORED today; PENDING is reserved for presigned-PUT direct upload (designed,
    # deferred — spec 102 §delivery).
    state: Mapped[str] = mapped_column(String(10), default=AttachmentState.STORED.value)
    # Plain UUID (no FK) — like events.actor_id, stays auth-schema-agnostic.
    created_by: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    @property
    def item_id(self) -> uuid.UUID | None:
        """The owning item for item-parented rows. KEPT for the EVENT payloads
        (service.py stamps it so notify/automations can item-scope); the REST
        field it also fed was dropped in RADD-895 — read entity_type/entity_id."""
        if self.entity_type == AttachmentParentType.ITEM.value:
            return self.entity_id
        return None


class AttachmentMoveJob(Base):
    """One background move of a host's attachments to another host (spec 102 §move):
    copy -> verify -> repoint -> best-effort source delete, per file."""

    __tablename__ = "attachment_move_jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_host_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("storage_hosts.id", ondelete="CASCADE")
    )
    target_host_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("storage_hosts.id", ondelete="CASCADE")
    )
    state: Mapped[str] = mapped_column(String(20), default=MoveJobState.PENDING.value)
    total: Mapped[int] = mapped_column(Integer, default=0)
    moved: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    # Capped list of {attachment_id, filename, detail} — enough to act on.
    problems: Mapped[list] = mapped_column(JSONB, default=list)
    created_by: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
