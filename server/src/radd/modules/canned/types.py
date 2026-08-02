from enum import StrEnum


class CannedToken(StrEnum):
    """The fixed variable set a canned body may reference (spec 66) — the
    render endpoint resolves each against the item context; `render_canned`
    leaves any token with no (or an empty) value verbatim."""

    ITEM_KEY = "item.key"
    ITEM_TITLE = "item.title"
    REPORTER_NAME = "reporter.name"
    REPORTER_EMAIL = "reporter.email"
    ASSIGNEE_NAME = "assignee.name"
    ME_NAME = "me.name"


class CannedEvent(StrEnum):
    CREATED = "canned_response.created"
    UPDATED = "canned_response.updated"
    DELETED = "canned_response.deleted"


class CannedEntity(StrEnum):
    CANNED_RESPONSE = "canned_response"
