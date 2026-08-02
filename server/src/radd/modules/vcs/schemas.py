import uuid

from pydantic import BaseModel, ConfigDict, Field

from .types import VcsProvider, VcsRefType
from radd.apitypes import UtcDatetime


class VcsLinkCreate(BaseModel):
    # item_id comes from the URL path, not the body.
    ref_type: VcsRefType
    provider: VcsProvider = VcsProvider.MANUAL
    title: str = Field(min_length=1, max_length=300)
    url: str = Field(min_length=1, max_length=2000)
    status: str = Field("", max_length=40)
    external_id: str = Field("", max_length=200)


class VcsLinkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    item_id: uuid.UUID
    ref_type: VcsRefType
    provider: VcsProvider
    title: str
    url: str
    status: str
    external_id: str
    created_by: uuid.UUID | None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    # Spec 111 — latest CI run for the ref ("" = never reported).
    ci_state: str = ""
    ci_url: str = ""
