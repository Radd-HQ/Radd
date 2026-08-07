"""Read-time resolution of a mail row against its kind's preset (RADD-969).

Pure functions of (row, `KIND_DEFAULTS`) — no session, no I/O — so every caller
that touches a connection detail (the poller, the SMTP sender, the registry's
completeness checks, the settings API) reads the same answer.

**The rule, copied from spec 110's `issuer_of`:** the ROW STORES BLANK where the
preset answers, and the value is resolved on the way out. A Gmail row therefore
has no host at all; upgrading the preset upgrades every existing row. Writing
`smtp.gmail.com` into the row at save time would look identical on the first day
and be wrong on the day the preset changes.

An explicit row value always wins — a preset is a default, not a lock. The one
exception is `starttls`, which is a boolean and so has no "unset": for a kind
whose transport the preset answers, the preset decides, because the form hides
that checkbox and a hidden control must not carry a stale value into behaviour.
"""

from __future__ import annotations

from email.utils import parseaddr

from .models import MailSender, MailSource
from .types import EMPTY_PRESET, KIND_DEFAULTS, MailKindPreset, MailSourceKind


def preset_for(kind: str) -> MailKindPreset:
    """The preset behind a kind. An unrecognised kind answers nothing rather
    than raising: a row written by a newer version must degrade, not crash the
    poller that is walking past it."""
    return KIND_DEFAULTS.get(kind, EMPTY_PRESET)


def _address(value: str) -> str:
    """The bare address out of `Radd <agent@example.com>`."""
    return parseaddr(value)[1].strip()


# --- senders --------------------------------------------------------------------


def sender_host(row: MailSender) -> str:
    return row.host or preset_for(row.kind).smtp_host


def sender_port(row: MailSender) -> int:
    return row.port or preset_for(row.kind).smtp_port


def sender_starttls(row: MailSender) -> bool:
    preset = preset_for(row.kind)
    return preset.smtp_starttls if preset.answers_smtp else row.starttls


def sender_username(row: MailSender) -> str:
    """Blank falls back to the sending identity — for Gmail and Outlook the
    login IS the mailbox address, so asking for it twice is a form asking a
    question it already knows the answer to."""
    if row.username:
        return row.username
    return _address(row.from_address) if preset_for(row.kind).answers_smtp else ""


# --- sources --------------------------------------------------------------------


def source_host(row: MailSource) -> str:
    return row.host or preset_for(row.kind).imap_host


def source_port(row: MailSource) -> int:
    return row.port or preset_for(row.kind).imap_port


def source_username(row: MailSource) -> str:
    if row.username:
        return row.username
    return _address(row.address) if preset_for(row.kind).answers_imap else ""


# --- completeness ----------------------------------------------------------------


def source_needs_host(row: MailSource) -> bool:
    """Whether saving this source without a host is a mistake worth refusing.

    A webhook has no host to speak of, and a preset kind carries its own — so
    the only row that needs one typed is a hand-configured IMAP mailbox.
    """
    if row.kind == MailSourceKind.WEBHOOK.value:
        return False
    return not source_host(row)


def sender_needs_host(row: MailSender) -> bool:
    return not sender_host(row)


def source_pollable(row: MailSource) -> bool:
    """Somewhere to connect and someone to connect as — after resolution, so a
    Gmail row holding nothing but an address and an app password counts."""
    return bool(source_host(row) and source_username(row))
