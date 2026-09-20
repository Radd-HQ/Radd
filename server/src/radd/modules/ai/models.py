"""AI provider registry tables (spec 101).

Providers moved out of the environment and into the database because the
env-only design could name exactly one endpoint and needed a redeploy to
change — while the features need SEVERAL models at once: a chat model for
editor actions, an embedding model for semantic search, a vision model for
storage routing (spec 102). Roles are rows, not JSONB, so deleting a provider
cascades its assignments away instead of leaving dangling references.
"""

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint, false, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin

from .types import AiProviderSource


class AiProviderRow(Base, TimestampMixin):
    """One reachable AI endpoint. The api_key is stored as-is (it must be replayed
    on every request — the webhook-secret precedent); reads expose `has_api_key`."""

    __tablename__ = "ai_providers"
    __table_args__ = (UniqueConstraint("name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    wire_shape: Mapped[str] = mapped_column(String(20))  # AiWireShape
    base_url: Mapped[str] = mapped_column(String(500), default="")  # "" = shape default
    api_key: Mapped[str] = mapped_column(Text, default="")
    default_model: Mapped[str] = mapped_column(String(200), default="")
    source: Mapped[str] = mapped_column(String(10), default=AiProviderSource.USER.value)
    # RADD-1273: Radd states its preference on every request rather than
    # relying on the server's chat template. `reasoning` OFF (the default for
    # every row) asks a thinking model not to think; `request_params` is an
    # admin-supplied JSON object deep-merged LAST into every chat payload, so
    # it can override anything Radd chose (temperature, vendor knobs).
    reasoning: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    request_params: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)


class AiModelRole(Base, TimestampMixin):
    """Assignment of one role (chat|embeddings|vision) to a provider + model."""

    __tablename__ = "ai_model_roles"

    role: Mapped[str] = mapped_column(String(20), primary_key=True)  # AiRole
    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_providers.id", ondelete="CASCADE")
    )
    model: Mapped[str] = mapped_column(String(200), default="")  # "" = provider default


class AiPresetPrompt(Base, TimestampMixin):
    """Admin-authored editor action (spec 103): a named prompt every user's AI menu
    offers. The prompt text never ships to the client — menus carry id + name."""

    __tablename__ = "ai_preset_prompts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    prompt: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
