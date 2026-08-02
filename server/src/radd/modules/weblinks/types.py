from enum import StrEnum


class WebLinkCategory(StrEnum):
    DOCUMENT = "document"
    DESIGN = "design"
    SPEC = "spec"
    EXTERNAL = "external"
    OTHER = "other"


class WebLinkEvent(StrEnum):
    CREATED = "weblink.created"
    UPDATED = "weblink.updated"
    DELETED = "weblink.deleted"


class WebLinkEntity(StrEnum):
    WEB_LINK = "web_link"
