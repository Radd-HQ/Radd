"""Read-time resolution of a mail row against its kind's preset (RADD-969), pure.

The row stores BLANK where the preset answers and the value is resolved on the
way out (spec 110's `issuer_of` rule), so upgrading a preset upgrades every row.
An explicit row value wins — except `starttls`, a boolean with no "unset": for a
preset kind the preset decides, because the form hides that checkbox.
"""

from __future__ import annotations

from email.utils import parseaddr

from .models import MailSender, MailSource
from .types import EMPTY_PRESET, KIND_DEFAULTS, MailKindPreset, MailSourceKind


def preset_for(kind: str) -> MailKindPreset:
    """The preset behind a kind; an unrecognised kind answers nothing, never raises."""
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
    """Blank falls back to the sending identity on a preset kind (the login IS the
    mailbox address)."""
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
    """Only a hand-configured IMAP mailbox needs a host typed (a webhook has none,
    a preset carries its own)."""
    if row.kind == MailSourceKind.WEBHOOK.value:
        return False
    return not source_host(row)


def sender_needs_host(row: MailSender) -> bool:
    return not sender_host(row)


def source_pollable(row: MailSource) -> bool:
    """Somewhere to connect and someone to connect as, after resolution."""
    return bool(source_host(row) and source_username(row))
