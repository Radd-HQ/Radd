class RaddError(Exception):
    """Base for domain errors any module may raise."""


class NotFoundError(RaddError):
    def __init__(self, entity: str, identifier: object):
        self.entity = entity
        self.identifier = identifier
        super().__init__(f"{entity} {identifier} not found")


class ConflictError(RaddError):
    """Domain conflict (409).

    Two message forms: `ConflictError(entity, identifier)` -> "<entity> <id> already
    exists" (duplicate creation), or `ConflictError(entity, reason="…")` -> the reason
    verbatim — so hierarchy/ownership violations don't get a bogus "already exists" suffix.
    """

    def __init__(self, entity: str, identifier: object = "", *, reason: str | None = None):
        self.entity = entity
        self.identifier = identifier
        message = f"{entity}: {reason}" if reason else f"{entity} {identifier} already exists"
        super().__init__(message)


class UnauthorizedError(RaddError):
    """No valid credentials (session cookie or bearer token). Handled as 401."""

    def __init__(self, message: str = "not authenticated"):
        super().__init__(message)


class ForbiddenError(RaddError):
    """Authenticated but not allowed to perform the action. Handled as 403."""

    def __init__(self, message: str = "forbidden"):
        super().__init__(message)
