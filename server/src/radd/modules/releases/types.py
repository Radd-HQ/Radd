from enum import StrEnum


class ReleaseStatus(StrEnum):
    PLANNED = "planned"
    RELEASED = "released"  # setting this stamps released_at server-side


class ReleaseEvent(StrEnum):
    CREATED = "release.created"
    UPDATED = "release.updated"
    DELETED = "release.deleted"


class ReleaseEntity(StrEnum):
    RELEASE = "release"
