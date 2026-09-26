"""What a notification SAYS — one vocabulary for the inbox and both email
channels (RADD-967/968). What it LOOKS like is `radd.mailrender`'s."""

from __future__ import annotations

import uuid

from radd import mailrender
from radd.config import settings

from .models import Notification
from .types import NotificationType

#: No resolvable actor: a clock (SLA timers) or the system (automations) did it.
UNKNOWN_ACTOR = "Someone"

#: The opening subject of a per-event email, until the item has a mail thread.
#: The bracketed key threads a reply whose client dropped the headers.
MAIL_SUBJECT_TEMPLATE = "[{key}] {title}"

#: Why a user is being written to — notify's own wording, as plain text, so
#: neither side learns the other's enum.
MAIL_REASON_TEMPLATE = "You are receiving this because you follow {key} — reply to this email to comment."


def headline(type_: NotificationType | str, actor: str, payload: dict) -> str:
    """The sentence for one notification. Every type gets its own — a shared
    fallback is how five of them ended up claiming someone commented."""
    if not isinstance(type_, NotificationType):
        try:
            type_ = NotificationType(type_)
        except ValueError:
            # RADD-1326: a plugin's kind rendered its own line when it was
            # written (`NotificationKindSpec.render`) — notify cannot know it.
            return str(payload.get("headline") or f"{actor}: {str(type_).replace('_', ' ')}")
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


#: Kinds whose subject is a PAGE: they carry the wiki payload and link its permalink.
_PAGE_KINDS = frozenset(
    {NotificationType.PAGE_UPDATED, NotificationType.PAGE_CREATED}
)


def actor_name(notification: Notification, actor_names: dict[uuid.UUID, str]) -> str:
    """Who did it — by id first: `page_updated` rows carry no `actor_name`."""
    return (
        actor_names.get(notification.actor_id)
        or (notification.payload or {}).get("actor_name")
        or UNKNOWN_ACTOR
    )


def entry(notification: Notification, actor_names: dict[uuid.UUID, str]) -> mailrender.DigestEntry:
    """One notification as a renderable line: headline, subject, excerpt, link."""
    payload = notification.payload or {}
    type_ = notification.type
    line = headline(type_, actor_name(notification, actor_names), payload)
    base = settings.app_base_url
    if type_ not in NotificationType.__members__.values() and payload.get("link"):
        # RADD-1326: a contributed kind names its own link (site-relative).
        link = str(payload["link"])
        return mailrender.DigestEntry(
            headline=line,
            subject=str(payload.get("subject") or ""),
            url=link if link.startswith("http") else base.rstrip("/") + "/" + link.lstrip("/"),
        )
    # RADD-1297: a notification about a comment links to the COMMENT.
    comment = payload.get("comment_id") or None
    if type_ in _PAGE_KINDS or (payload.get("page_number") and not payload.get("item_key")):
        # The permalink (RADD-1233). A page COMMENT (commented/mentioned with a
        # page payload) is a page line too.
        key = payload.get("page_number")
        return mailrender.DigestEntry(
            headline=line,
            subject=payload.get("title") or "",
            url=mailrender.page_url(base, key, comment=comment) if key else "",
        )
    key = payload.get("item_key") or ""
    title = payload.get("item_title") or ""
    return mailrender.DigestEntry(
        headline=line,
        # An itemless automation notification has no key: no subject, no link.
        subject=f"[{key}] {title}".strip() if key else "",
        excerpt=payload.get("excerpt") or "",
        url=mailrender.issue_url(base, key, comment=comment) if key else "",
    )
