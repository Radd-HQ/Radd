"""Credential-aware principal checks shared by all administrative surfaces."""

from radd.exceptions import ForbiddenError

from .models import User
from .types import InstanceRole, Permission


def is_instance_admin(user: User) -> bool:
    """An active admin whose credential permits the administrative bypass."""
    if not getattr(user, "active", True) or user.instance_role != InstanceRole.ADMIN:
        return False
    scope = getattr(user, "token_scope", None)
    return scope is None or Permission.GLOBAL_MANAGE in scope.allowed(None)


def require_account_session(user: User) -> None:
    """Credentials and account security are managed through a human session.

    A key must never mint a replacement with broader scope or a later expiry,
    change MFA, or revoke another credential belonging to its account.
    Internal callers provisioning service-account keys have no API principal.
    """
    if getattr(user, "api_token_id", None) is not None or user.token_scope is not None:
        raise ForbiddenError("account security requires a browser session")
