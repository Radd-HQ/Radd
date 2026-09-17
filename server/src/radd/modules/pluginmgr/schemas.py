from pydantic import BaseModel


class PluginCapabilityRead(BaseModel):
    """One evaluated CapabilitySpec on a plugin row — `enabled` is the runtime
    configured-ness (e.g. a connector's env token present), NOT the plugin's
    lifecycle state."""

    key: str
    label: str
    category: str
    enabled: bool


class PluginRead(BaseModel):
    id: str
    name: str
    version: str
    core: bool
    state: str
    description: str
    can_toggle: bool
    capabilities: list[PluginCapabilityRead] = []
    active: bool = False
    restart_required: bool = False
    origin: str = "builtin"
    dependencies: list[str] = []
    problems: list[str] = []


class ContributionSettings(BaseModel):
    """The set of a plugin's UI contributions disabled INSTANCE-WIDE (spec 94), each a
    `"<slot>::<id>"` key. A globally-disabled contribution is hidden for everyone and never
    offered for per-user override. Admin-writable per plugin; readable by anyone."""

    disabled: list[str] = []
