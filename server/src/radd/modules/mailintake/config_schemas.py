"""Wire shapes for Settings → Email (RADD-958). Secrets are write-only: reads
carry `has_secret`, never the value. On update an OMITTED secret is unchanged
(`model_fields_set`) and an explicit "" clears it.
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
    """What the add form needs to prefill itself (RADD-969). `host`/`port`/
    `starttls` are IMAP under `sources`, SMTP under `senders`. `preset` true = the
    connection is answered, so the form HIDES those fields (an edited value would
    outlive the preset)."""

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
    #: RAW, as stored (blank on a preset kind), so a round trip does not freeze it.
    host: str
    port: int
    username: str
    folder: str
    default_project_id: uuid.UUID | None
    #: "Send replies from" (RADD-979) — NULL means the default sender.
    sender_id: uuid.UUID | None = None
    #: The trusted `Authentication-Results` authserv-id (RADD-1032); blank = trust nothing.
    trusted_authserv_id: str | None = None
    has_secret: bool
    rule_count: int = 0
    #: What the poller will use (RADD-969); the LIST reads these, the FORM the raw ones.
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
    #: 0 = unset, so the preset answers.
    port: int = DEFAULT_IMAP_PORT
    username: str = ""
    folder: str = DEFAULT_IMAP_FOLDER
    default_project_id: uuid.UUID | None = None
    #: The sender that answers for this address (RADD-979); None = the default.
    sender_id: uuid.UUID | None = None
    #: The authserv-id to trust (RADD-1032); "" / None = trust nothing.
    trusted_authserv_id: str | None = None
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
    #: `{prompt, answers: [{answer, project_id}]}` — validated by the handler.
    config: dict = Field(default_factory=dict)
    project_id: uuid.UUID | None = None
    position: float | None = None


class MailRuleReorder(BaseModel):
    """Full ordered list of rule ids — one intent, never a half-ordered chain."""

    rule_ids: list[uuid.UUID]


class MailTestRequest(BaseModel):
    to_address: str = Field(min_length=3, max_length=320)


class MailTestResult(BaseModel):
    """What a test send did; `message_id` is the one the RELAY reported (RADD-955)."""

    ok: bool
    message_id: str = ""
    error: str = ""


class RoutingPreviewRequest(BaseModel):
    """Ask the chain where a message WOULD go, without sending one."""

    recipient: str = ""
    sender: str = ""
    subject: str = ""
    body: str = ""


class RoutingRuleOutcome(BaseModel):
    """One rule's verdict on the sample message (a `MailRuleStatus` value)."""

    rule_id: uuid.UUID | None = None
    rule_name: str = ""
    status: str = ""
    detail: str = ""


class RoutingPreviewResult(BaseModel):
    project_id: uuid.UUID | None
    project_key: str = ""
    matched_rule_id: uuid.UUID | None = None
    matched_rule_name: str = ""
    reason: str = ""
    #: The whole chain, in order: consulted, skipped (disabled) or never reached.
    outcomes: list[RoutingRuleOutcome] = []
