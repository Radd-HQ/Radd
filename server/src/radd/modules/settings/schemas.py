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
    value: Any = None  # null for a secret: its value never leaves the server (RADD-1454)
    # RADD-1454, secrets only: whether a non-empty value is in effect (from a row at this
    # scope, a wider one, or the environment). Null on every other row.
    set: bool | None = None
    set_here: bool  # an override exists at this exact scope (vs. inherited)
    default: Any = None  # the env/config fallback, for "reset to default"; null for a secret
    # Enumerated settings only (spec 107 cleanup): the accepted values — the
    # editor renders a select instead of a free-text input.
    choices: list[str] | None = None
    # Sealed at rest and never read back (RADD-1424/RADD-1454): the editor shows `set`
    # and takes a replacement; an empty write keeps the stored value.
    secret: bool = False
    # RADD-1368: prose — the editor renders a textarea.
    multiline: bool = False
    # RADD-930: the settings surface this key belongs on ("" = the General page).
    # Declared by the owning plugin so placement travels with the setting.
    section: str = ""
    # RADD-1390: the owning plugin renders it on its own page at this scope, so
    # the scope's General page leaves it out.
    homed: bool = False


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
