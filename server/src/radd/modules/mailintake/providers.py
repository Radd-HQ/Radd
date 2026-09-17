"""The two provider seams (RADD-958).

    MailSource   where mail comes IN   — webhook (deployed), imap (shipped), gmail (next)
    MailSender   where mail goes OUT   — smtp (deployed), gmail (next)

**These exist so a Gmail adapter is a new class rather than a rewrite.** The test
of whether they are real is not that they are Protocols — it is that everything
which could accidentally become webhook-only lives behind them: dedup, threading,
quote stripping, attachment capture and the loop guards are all in `intake`, and
a source contributes transport and authentication and nothing else.

`MailSender.send` returning the sent Message-ID is the load-bearing part of the
outbound seam, not a detail. SMTP lets a client choose its own id; the Gmail API
assigns one. A sender that reported its intended id would make every reply
arrive unthreaded, and nothing would raise.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from radd.mailtypes import MailAttachment


@dataclass(frozen=True)
class RawMessage:
    """One message as a source hands it over. Nothing is parsed yet —
    the source's whole job is to produce this and prove it is authentic."""

    raw: bytes
    envelope_from: str = ""
    envelope_to: str = ""
    #: The provider's own idea of the Message-ID, when it supplies one out of
    #: band (Cloudflare sends `X-Radd-Message-Id`). The parsed header wins when
    #: both exist — it is what a replying client will actually quote.
    message_id_hint: str = ""


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
        """Return the ACTUAL Message-ID. See the module docstring — this is the
        value threading is stored against, and it is not always the one the
        caller composed."""
        ...


@runtime_checkable
class MailSource(Protocol):
    """Produces authenticated raw messages. A push source verifies a signature
    and yields one; a pull source polls and yields many."""

    kind: str

    async def fetch(self) -> Sequence[RawMessage]:
        """Messages waiting to be taken in. A push source returns nothing here —
        its messages arrive through its own endpoint."""
        ...
