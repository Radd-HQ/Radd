import re
from dataclasses import dataclass
from enum import StrEnum

# AD's transitive-membership matching rule (LDAP_MATCHING_RULE_IN_CHAIN):
# `memberOf:<rule>:=<group DN>` matches NESTED membership — a plain memberOf
# comparison only sees direct groups.
LDAP_MATCHING_RULE_IN_CHAIN = "1.2.840.113556.1.4.1941"

# sAMAccountName shape; anything else is refused before it reaches the wire,
# so no DN or filter syntax can ride in on the username.
USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{1,64}$")


class LdapEvent(StrEnum):
    LOGIN = "ldap.login"  # a successful directory sign-in (audit)


class LdapEntity(StrEnum):
    LDAP = "ldap"


class DirectoryUnreachable(Exception):
    """The directory could not be asked (spec 87) — connection refused, bind
    rejected, timeout.

    Kept distinct from "the group is not there" because the two must NEVER be
    confused: a missing group flags a team as stale, and an unreachable DC must
    not. `get_group` used to answer None for both.
    """


class ImportMatchKind(StrEnum):
    """Why an incoming directory user was tied to an existing account (spec 88).

    Radd accounts have no username column — identity IS the email — so an AD
    `sAMAccountName` can only be compared against the local part of one.
    """

    EMAIL = "email"  # exact address: certainly the same account
    USERNAME = "username"  # sAMAccountName == an existing email's local part
    NAME = "name"  # exact case-insensitive display name


class ImportStatus(StrEnum):
    """What importing one directory user would run into (spec 88)."""

    NEW = "new"  # nothing matches — a plain create
    LINKED = "linked"  # the exact email already exists; import refreshes it
    CONFLICT = "conflict"  # looks like an existing person under a DIFFERENT email


class ImportResolution(StrEnum):
    """What the admin chose to do about one incoming directory user (spec 88).

    OVERWRITE and MERGE both end with the DIRECTORY as the source of truth —
    they differ in how many Radd accounts are involved.
    """

    CREATE = "create"  # make a new account, leaving the look-alike alone
    SKIP = "skip"  # import nothing for this person
    OVERWRITE = "overwrite"  # one account: adopt AD's email/name onto it, id preserved
    MERGE = "merge"  # two accounts: fold the look-alike into the AD-identified one


class SyncKind(StrEnum):
    """`directory_sync_state.kind` (spec 85) — one row per periodic sync."""

    USER_SYNC = "user_sync"
    GROUP_SYNC = "group_sync"


@dataclass(frozen=True)
class DirectoryUser:
    """What one authenticated directory round-trip yields."""

    username: str
    email: str
    name: str
    is_admin: bool
    # Spec 84: of the linked-team group DNs probed during login, the ones this
    # user is a (possibly nested) member of. Empty for enumeration results.
    team_group_dns: frozenset[str] = frozenset()


@dataclass(frozen=True)
class DirectoryGroup:
    """One AD group from the service-account group search (spec 84).
    member_count is the DIRECT `member` attribute length — cheap for display;
    the sync itself resolves membership transitively. `member_of` (RADD-831)
    is the group's DIRECT parents — the nesting edges the old sync resolved
    transitively and threw away."""

    cn: str
    dn: str
    description: str
    member_count: int
    member_of: tuple[str, ...] = ()
