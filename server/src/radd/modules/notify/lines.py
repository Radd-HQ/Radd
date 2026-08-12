"""What a notification SAYS — one vocabulary, two channels (RADD-967, RADD-968).

This module owns `NotificationType`, so every type's sentence belongs here. What
they LOOK like is `radd.mailrender`'s decision; this file only ever produces
words and a `DigestEntry`.

It was `emailer._headline`/`_entry`, private to the digest. RADD-968 gave notify
a SECOND email channel — the per-event mailer — and two renderings of "Ada
commented" is exactly how the digest came to have four sentences for nine types
in the first place. So the vocabulary moved out of the loop that happened to be
written first, and both loops read it.
"""

from __future__ import annotations

import uuid

from radd import mailrender
from radd.config import settings

from .models import Notification
from .types import NotificationType

#: No resolvable actor: a clock (SLA timers) or the system (automations) did it.
UNKNOWN_ACTOR = "Someone"

#: The opening subject of a per-event email, used only until the item has a mail
#: thread — after that the transport prefers the thread's own (see
#: `mailintake.transport`). Shaped like the ack's, because the bracketed key is
#: what threads a reply typed by someone whose client dropped the headers.
MAIL_SUBJECT_TEMPLATE = "[{key}] {title}"

#: Why a user is being written to. Notify's own wording, deliberately not
#: imported from `mailintake.types`: the reason is a property of WHY THIS MODULE
#: is mailing you, and mailrender takes it as plain text precisely so neither
#: side has to learn the other's enum.
MAIL_REASON_TEMPLATE = "You are receiving this because you follow {key} — reply to this email to comment."


def headline(type_: NotificationType, actor: str, payload: dict) -> str:
    """The sentence for one notification. Every type gets its own — a shared
    fallback is how five of them ended up claiming someone commented."""
    if type_ is NotificationType.ASSIGNED:
        return f"{actor} assigned you"
    if type_ is NotificationType.MENTIONED:
        source = payload.get("source")
        return f"{actor} mentioned you in the {source}" if source else f"{actor} mentioned you"
    if type_ is NotificationType.STATE_CHANGED:
        return f"{actor} moved {payload.get('from') or '?'} → {payload.get('to') or '?'}"
    if type_ is NotificationType.COMMENTED:
        return f"{actor} commented"
    if type_ in (NotificationType.SLA_BREACH, NotificationType.SLA_DUE_SOON):
        state = "breached" if type_ is NotificationType.SLA_BREACH else "due soon"
        # `kind` (response/resolution) is absent on older rows — joined rather
        # than interpolated so its absence costs no double space.
        target = " ".join(filter(None, ("SLA", payload.get("kind"), "target", state)))
        return f"{target} ({payload.get('policy') or 'policy'})"
    if type_ is NotificationType.AUTOMATION:
        # The rule already rendered its own message; the rule NAME is the
        # fallback, because a rule with an empty template is still worth seeing.
        return str(payload.get("message") or f'Rule "{payload.get("rule") or "?"}" fired')
    if type_ is NotificationType.APPROVAL:
        target = payload.get("to_state") or "?"
        action = payload.get("action")
        if action == "approved":
            return f"{actor} approved the move to {target}"
        if action == "declined":
            return f"{actor} declined the move to {target}"
        return f"{actor} requested your approval to move to {target}"
    if type_ is NotificationType.PARTICIPANT_ADDED:
        # No object named here either: the issue is the line's SUBJECT and its
        # link (`entry` renders "[KEY] Title" beside it), so this reads as one
        # sentence with what follows it (RADD-978).
        return f"{actor} added you to the issue"
    if type_ is NotificationType.PAGE_UPDATED:
        # The page's title is the line's SUBJECT (and its link), so naming it
        # here too would print it twice — `entry` (RADD-719).
        return f"{actor} edited the page"
    if type_ is NotificationType.PAGE_CREATED:
        return f"{actor} created the page"
    # Spec 118's ambient pair. These reach SUBSCRIBERS — someone who asked about
    # a project, a space or a team rather than about this row — so the sentence
    # says what happened and lets the subject line say what it happened to.
    if type_ is NotificationType.CREATED:
        return f"{actor} filed"
    if type_ is NotificationType.UPDATED:
        fields = payload.get("fields") or []
        named = ", ".join(str(field) for field in fields[:3])
        return f"{actor} updated {named}" if named else f"{actor} updated the issue"
    # A type added without a line lands here NAMED, rather than silently reading
    # as whichever branch happened to be last.
    return f"{actor}: {type_.value.replace('_', ' ')}"


#: Notification kinds whose subject is a PAGE, not an issue — they carry the
#: wiki payload (`space_slug`/`page_slug`/`title`) and link into `/pages/`.
_PAGE_KINDS = frozenset(
    {NotificationType.PAGE_UPDATED, NotificationType.PAGE_CREATED}
)


def actor_name(notification: Notification, actor_names: dict[uuid.UUID, str]) -> str:
    """Who did it. The id resolves first because `page_updated` notifications
    never carried `actor_name` in their payload (pages writes its own), so every
    wiki line read "Someone edited …"."""
    return (
        actor_names.get(notification.actor_id)
        or (notification.payload or {}).get("actor_name")
        or UNKNOWN_ACTOR
    )


def entry(notification: Notification, actor_names: dict[uuid.UUID, str]) -> mailrender.DigestEntry:
    """One notification as a renderable line: headline, subject, excerpt, link."""
    payload = notification.payload or {}
    type_ = NotificationType(notification.type)
    line = headline(type_, actor_name(notification, actor_names), payload)
    base = settings.app_base_url
    if type_ in _PAGE_KINDS:
        space, page = payload.get("space_slug"), payload.get("page_slug")
        return mailrender.DigestEntry(
            headline=line,
            subject=payload.get("title") or "",
            url=mailrender.page_url(base, space, page) if space and page else "",
        )
    key = payload.get("item_key") or ""
    title = payload.get("item_title") or ""
    return mailrender.DigestEntry(
        headline=line,
        # Automation notifications carry neither (their payload is message+rule),
        # so the line degrades to the message with no link rather than to a
        # `/issues/` URL with nothing after it.
        subject=f"[{key}] {title}".strip() if key else "",
        excerpt=payload.get("excerpt") or "",
        url=mailrender.issue_url(base, key) if key else "",
    )
