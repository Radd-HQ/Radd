"""Wire shapes for Settings → Email (RADD-958).

**Secrets are write-only.** Every read model carries `has_secret: bool` and never
the value — the same rule Storage, Sign-in and AI follow. An admin who needs to
know the password should read it from wherever they store passwords, not from a
settings screen that anyone with the atom can open.

An omitted secret on update means "leave it alone", which is what makes editing a
port without re-typing a password possible. That is `model_fields_set`, not a
sentinel: an explicit empty string is a deliberate "clear it".
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from .types import (
    DEFAULT_IMAP_FOLDER,
    DEFAULT_IMAP_PORT,
    DEFAULT_SMTP_PORT,
    MailRuleType,
    MailSenderKind,
    MailSourceKind,
)


class MailKindInfo(BaseModel):
    """What the add-a-source / add-a-sender form needs to prefill itself
    (RADD-969) — the spec-110 `GET /sso/kinds` shape.

    `host`/`port`/`starttls` describe the kind's TRANSPORT for the half this
    entry belongs to: IMAP under `sources`, SMTP under `senders`. `preset` is
    the one the form branches on — true means the connection is answered, so
    those fields are hidden rather than shown pre-filled: a field showing
    `imap.gmail.com` invites someone to edit it, and the edited value would then
    outlive the preset.
    """

    #: A `MailSourceKind` value under `sources`, a `MailSenderKind` under `senders`.
    kind: str
    name: str
    summary: str = ""
    host: str = ""
    port: int = 0
    starttls: bool = True
    #: The operational precondition (app passwords), when there is one.
    guidance: str = ""
    help_url: str = ""
    preset: bool = False


class MailKinds(BaseModel):
    """Both halves in one response — the two dialogs share a query."""

    sources: list[MailKindInfo]
    senders: list[MailKindInfo]


class MailSourceRead(BaseModel):
    id: uuid.UUID
    name: str
    kind: MailSourceKind
    enabled: bool
    address: str
    #: RAW, as stored — blank on a preset kind, which is what the edit form has
    #: to show so a saved round trip does not freeze the preset into the row.
    host: str
    port: int
    username: str
    folder: str
    default_project_id: uuid.UUID | None
    has_secret: bool
    rule_count: int = 0
    #: What the poller will actually use (RADD-969) — row value or the kind's
    #: preset. The LIST reads these; the FORM reads the raw ones above.
    resolved_host: str = ""
    resolved_port: int = 0
    resolved_username: str = ""


class MailSourceWrite(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: MailSourceKind
    enabled: bool = True
    address: str = ""
    #: Blank on a preset kind. A stored value overrides the preset.
    host: str = ""
    #: 0 = unset, so the preset answers. Non-zero overrides it.
    port: int = DEFAULT_IMAP_PORT
    username: str = ""
    folder: str = DEFAULT_IMAP_FOLDER
    default_project_id: uuid.UUID | None = None
    #: Omitted = unchanged. "" = clear.
    secret: str | None = None


class MailSenderRead(BaseModel):
    id: uuid.UUID
    name: str
    kind: MailSenderKind
    enabled: bool
    is_default: bool
    from_address: str
    reply_to: str
    host: str
    port: int
    username: str
    starttls: bool
    has_secret: bool
    resolved_host: str = ""
    resolved_port: int = 0
    resolved_username: str = ""
    resolved_starttls: bool = True


class MailSenderWrite(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: MailSenderKind = MailSenderKind.SMTP
    enabled: bool = True
    is_default: bool = False
    from_address: str = ""
    reply_to: str = ""
    host: str = ""
    port: int = DEFAULT_SMTP_PORT
    username: str = ""
    starttls: bool = True
    secret: str | None = None


class MailRuleRead(BaseModel):
    id: uuid.UUID
    source_id: uuid.UUID
    name: str
    rule_type: MailRuleType
    enabled: bool
    position: float
    config: dict
    project_id: uuid.UUID | None


class MailRuleWrite(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    rule_type: MailRuleType
    enabled: bool = True
    #: Per-type: `{addresses: []}` / `{patterns: []}` / `{contains: []}` /
    #: `{prompt, answers: [{answer, project_id}]}`. Loosely typed on purpose —
    #: a plugin's rule kind brings its own shape, and the handler validates.
    config: dict = Field(default_factory=dict)
    project_id: uuid.UUID | None = None
    position: float | None = None


class MailRuleReorder(BaseModel):
    """Full ordered list of rule ids. Sent whole rather than as a pair of
    swapped positions: a drag reorder is one intent, and applying it as N
    independent updates leaves a half-ordered chain if one fails."""

    rule_ids: list[uuid.UUID]


class MailTestRequest(BaseModel):
    to_address: str = Field(min_length=3, max_length=320)


class MailTestResult(BaseModel):
    """What a test send actually did. `message_id` is the one the RELAY
    reported, which is the value threading depends on (RADD-955) — showing it
    turns 'did that work' into something an admin can verify."""

    ok: bool
    message_id: str = ""
    error: str = ""


class RoutingPreviewRequest(BaseModel):
    """Ask the chain where a message WOULD go, without sending one.

    Storage learned this the hard way: an ordered rule chain nobody can dry-run
    makes "why did this land there" unanswerable, so its page shows which rule
    captured an upload. Same here.
    """

    recipient: str = ""
    sender: str = ""
    subject: str = ""
    body: str = ""


class RoutingPreviewResult(BaseModel):
    project_id: uuid.UUID | None
    project_key: str = ""
    matched_rule_id: uuid.UUID | None = None
    matched_rule_name: str = ""
    reason: str = ""
