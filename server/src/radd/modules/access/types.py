"""Vocabulary for the generic access-grant framework (spec 92).

One primitive for resource-level access control across the whole app: a SUBJECT
(user | team | role) is granted an ACCESS (read | write | …) on a RESOURCE
(resource_type + id), SCOPED to a project (NULL = everywhere the resource
applies) or a set of them. Any module or plugin registers its resource type +
authz hook and gets the generic /grants API and the reusable GrantsEditor for
free — no per-surface grant code.
"""

from enum import StrEnum


class GrantSubject(StrEnum):
    """Who a grant is given to. Uniform across every grant surface."""

    USER = "user"
    TEAM = "team"
    ROLE = "role"


class Access(StrEnum):
    """The capability a grant confers. Read/write are the common pair (fields);
    a resource may declare its own set (e.g. views' viewer/editor/owner) — the
    column is a free string validated against the resource's ResourceSpec."""

    READ = "read"
    WRITE = "write"


class AccessEntity(StrEnum):
    GRANT = "access_grant"


class AccessEvent(StrEnum):
    GRANTED = "access.granted"
    REVOKED = "access.revoked"
