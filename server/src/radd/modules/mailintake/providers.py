"""The outbound provider seam (RADD-958). `MailSender.send` returns the
Message-ID that actually went on the wire — SMTP honours a client-set id, the
Gmail API replaces it, and threading is stored against the real one. A sender
that reported its intended id would make every reply arrive unthreaded, and
nothing would raise.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from radd.mailtypes import MailAttachment


@dataclass(frozen=True)
class OutboundMessage:
    """One message a sender is asked to deliver.

    `body` is the plain-text part; `html_body` the optional richer rendering of
    the SAME content (RADD-967). Both are composed by `radd.mailrender`, so a
    sender never decides what a message looks like — only how it travels.
    """

    to_address: str
    subject: str
    body: str
    to_name: str = ""
    html_body: str = ""
    headers: Mapping[str, str] = field(default_factory=dict)
    attachments: tuple[MailAttachment, ...] = ()


@runtime_checkable
class MailSender(Protocol):
    """Delivers one message and reports the Message-ID that went on the wire."""

    kind: str

    async def send(self, message: OutboundMessage) -> str:
        """Return the ACTUAL Message-ID (see the module docstring)."""
        ...

