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

from .types import MailRuleType, MailSenderKind, MailSourceKind


class MailSourceRead(BaseModel):
    id: uuid.UUID
    name: str
    kind: MailSourceKind
    enabled: bool
    address: str
    host: str
    port: int
    username: str
    folder: str
    default_project_id: uuid.UUID | None
    has_secret: bool
    rule_count: int = 0


class MailSourceWrite(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: MailSourceKind
    enabled: bool = True
    address: str = ""
    host: str = ""
    port: int = 993
    username: str = ""
    folder: str = "INBOX"
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


class MailSenderWrite(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: MailSenderKind = MailSenderKind.SMTP
    enabled: bool = True
    is_default: bool = False
    from_address: str = ""
    reply_to: str = ""
    host: str = ""
    port: int = 587
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
