from typing import Any

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class InstalledPlugin(Base, TimestampMixin):
    """The source of truth for a non-core plugin's lifecycle state (§10). Its `id`
    is the plugin id (e.g. `radd.milestones`). Core plugins are NOT rows here — they
    are always enabled from `config.modules`."""

    __tablename__ = "installed_plugins"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    version: Mapped[str] = mapped_column(String(50), default="")
    state: Mapped[str] = mapped_column(String(20))  # PluginState
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
