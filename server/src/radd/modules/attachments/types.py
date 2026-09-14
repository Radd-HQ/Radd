from enum import StrEnum


class AttachmentEvent(StrEnum):
    CREATED = "attachment.created"
    DELETED = "attachment.deleted"
    # Spec 123: storage administration (hosts + routing rules) with old → new;
    # credentials appear only as "changed". Where bytes go, and who decided.
    HOST_CREATED = "storage_host.created"
    HOST_UPDATED = "storage_host.updated"
    HOST_DELETED = "storage_host.deleted"
    RULE_CREATED = "storage_rule.created"
    RULE_UPDATED = "storage_rule.updated"
    RULE_DELETED = "storage_rule.deleted"


class AttachmentEntity(StrEnum):
    ATTACHMENT = "attachment"
    HOST = "storage_host"
    RULE = "storage_rule"
    MOVE_JOB = "storage_move_job"


class StorageHostType(StrEnum):
    FILESYSTEM = "filesystem"
    S3 = "s3"


class DeliveryMode(StrEnum):
    """How bytes reach the browser: through the API, or straight from the host
    via a short presigned URL (spec 102 — presigned is what makes a zoned host's
    content unreachable to users whose packets can't route there)."""

    PROXY = "proxy"
    PRESIGNED = "presigned"


class StorageHostSource(StrEnum):
    ENV = "env"
    USER = "user"


class AttachmentState(StrEnum):
    STORED = "stored"
    PENDING = "pending"  # reserved: presigned-PUT direct upload (designed, deferred)


class AttachmentParentType(StrEnum):
    """Kernel entity vocabulary — matches event entity types, not table names."""

    ITEM = "item"
    PAGE = "page"
    #: RADD-800 — a per-person staging area, so a submission can carry files
    #: before the item it will hang off exists. Repointed to ITEM at submit.
    FORM_SUBMISSION = "form_submission"


class RuleType(StrEnum):
    """Builtin routing-rule types; plugins contribute more via the
    STORAGE_ROUTING_RULE socket (spec 102)."""

    USER_CHOICE = "user_choice"
    CIDR = "cidr"
    LLM = "llm"


class MoveJobState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    DONE_WITH_FAILURES = "done_with_failures"
    FAILED = "failed"
    CANCELED = "canceled"


class AttachmentTooLarge(Exception):
    """Upload exceeds RADD_ATTACHMENT_MAX_BYTES — handled as HTTP 413."""

    def __init__(self, limit: int):
        super().__init__(f"attachment exceeds the {limit} byte limit")


# Content types served inline (anything else downloads — hostile HTML/SVG must
# never render in-origin; svg is scriptable, so it downloads too).
INLINE_CONTENT_PREFIX = "image/"
NON_INLINE_IMAGE_TYPES = frozenset({"image/svg+xml"})


def serves_inline(content_type: str) -> bool:
    normalized = content_type.lower().split(";", 1)[0].strip()
    return normalized.startswith(INLINE_CONTENT_PREFIX) and normalized not in NON_INLINE_IMAGE_TYPES
