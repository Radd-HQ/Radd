import uuid

from pydantic import BaseModel, ConfigDict, Field

from radd.apitypes import UtcDatetime

from .types import DeliveryMode, RuleType, StorageHostType


class AttachmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    # Owning item for item-parented rows (property on the model) — kept so every
    # pre-102 consumer of the API works unchanged; None for wiki-parented files.
    item_id: uuid.UUID | None
    entity_type: str
    entity_id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    created_by: uuid.UUID | None
    created_at: UtcDatetime
    # Any spec-92 grant rows exist -> drives the lock badge (spec 102 ACL).
    restricted: bool = False
    # Where the bytes live — filled by the routers ("which storage did my
    # paste go to?" must be answerable from the UI).
    storage_host_name: str = ""


class StorageHostCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    host_type: StorageHostType
    endpoint: str = Field(default="", max_length=500)  # s3: host:port, no scheme
    access_key: str = Field(default="", max_length=200)
    secret_key: str = ""
    bucket: str = Field(default="", max_length=200)
    region: str = Field(default="", max_length=100)
    secure: bool = False
    root_dir: str = Field(default="", max_length=500)  # filesystem only; "" = env default
    delivery_mode: DeliveryMode = DeliveryMode.PROXY
    presign_expiry_seconds: int | None = Field(default=None, ge=30, le=86400)
    user_selectable: bool = False
    is_default: bool = False


class StorageHostUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    endpoint: str | None = Field(default=None, max_length=500)
    access_key: str | None = Field(default=None, max_length=200)
    # "" on update = keep the stored key (reads are redacted).
    secret_key: str | None = None
    bucket: str | None = Field(default=None, max_length=200)
    region: str | None = Field(default=None, max_length=100)
    secure: bool | None = None
    root_dir: str | None = Field(default=None, max_length=500)
    delivery_mode: DeliveryMode | None = None
    presign_expiry_seconds: int | None = Field(default=None, ge=30, le=86400)
    user_selectable: bool | None = None
    is_default: bool | None = None


class UploadOption(BaseModel):
    id: uuid.UUID
    name: str


class UploadContextRead(BaseModel):
    ask_user: bool
    options: list[UploadOption]
    # Named when an earlier chain rule would capture these files, so the SPA
    # can hint WHY there was no prompt ("routed by rule 'Content'").
    preempted_by: str | None = None


class StorageRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    rule_type: "RuleType"
    config: dict = {}
    enabled: bool = True


class StorageRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    config: dict | None = None
    enabled: bool | None = None


class StorageRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    rule_type: str
    position: int
    enabled: bool
    config: dict


class StorageRuleOrder(BaseModel):
    ids: list[uuid.UUID]


class StorageHostRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    host_type: str
    endpoint: str
    access_key: str
    has_secret_key: bool
    bucket: str
    region: str
    secure: bool
    root_dir: str
    delivery_mode: str
    presign_expiry_seconds: int | None
    user_selectable: bool
    is_default: bool
    source: str
    # Filled by the admin router from one grouped count query.
    attachment_count: int = 0
    total_bytes: int = 0
