import uuid

from pydantic import BaseModel, ConfigDict

from radd.apitypes import UtcDatetime


class GroupRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dn: str
    name: str
    #: Spec 87's health signal: set = the DN stopped resolving in AD; grants
    #: are kept and sync removals held while it stands.
    directory_missing_since: UtcDatetime | None = None
    direct_member_count: int = 0
    #: RADD-833 — the number a grant on this group RESOLVES to (nesting
    #: included). The direct count under-sells nested groups.
    transitive_member_count: int = 0
    parent_names: list[str] = []
    child_names: list[str] = []
