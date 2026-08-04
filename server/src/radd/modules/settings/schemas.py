import uuid
from typing import Any

from pydantic import BaseModel

from .types import SettingKey, SettingScope


class ScopedSettingRead(BaseModel):
    """One registered setting's effective value at a scope (feeds the settings UI)."""

    key: str
    type: str
    label: str
    description: str
    value: Any
    set_here: bool  # an override exists at this exact scope (vs. inherited)
    default: Any  # the env/config fallback, for "reset to default" affordances
    # Enumerated settings only (spec 107 cleanup): the accepted values — the
    # editor renders a select instead of a free-text input.
    choices: list[str] | None = None
    # RADD-846: the editor masks the input (the value itself stays admin-readable).
    secret: bool = False


class ScopedSettingWrite(BaseModel):
    scope: SettingScope
    scope_id: uuid.UUID | None = None  # project id; omitted for instance
    key: SettingKey
    value: Any


class ResolvedSetting(BaseModel):
    """GET /scoped-settings/resolve — one key's cascade-resolved value (spec 70):
    the project override if any, else the instance override, else the env default."""

    key: str
    value: Any
