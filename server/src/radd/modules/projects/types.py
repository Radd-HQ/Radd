from enum import StrEnum


class ProjectEvent(StrEnum):
    PROJECT_CREATED = "project.created"
    #: RADD-1009: name/description edited (`changes` in the payload; the key
    #: never changes, so it is never in there).
    PROJECT_UPDATED = "project.updated"


class ProjectEntity(StrEnum):
    PROJECT = "project"
