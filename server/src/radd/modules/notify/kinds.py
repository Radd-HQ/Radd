"""The matrix's ROWS: every core notification kind, labelled and classified
(spec 118), served to the SPA by the preferences endpoint.

A PERSONAL kind is addressed AT someone by the event (assigned, mentioned,
approval, …) and resolves through `own` alone; an AMBIENT kind reaches you
through a relationship the matrix's columns enumerate. Getting this wrong ends
approvals silently: approvers are often neither assignee nor watcher.
"""

from radd.kernel import NotificationKindSpec, registries

from .types import Channel, NotificationType

#: Every kind, in the order the settings page lists them: personally-directed
#: first (the ones nobody should have to hunt for), then the ambient stream.
NOTIFICATION_KINDS: tuple[NotificationKindSpec, ...] = (
    NotificationKindSpec(
        NotificationType.ASSIGNED.value,
        "Assigned to me",
        "An issue was assigned to you.",
        personal=True,
        default_channel=Channel.BOTH.value,
    ),
    NotificationKindSpec(
        NotificationType.MENTIONED.value,
        "Mentions",
        "Someone @-named you in a description or a comment.",
        personal=True,
        default_channel=Channel.BOTH.value,
    ),
    NotificationKindSpec(
        NotificationType.PARTICIPANT_ADDED.value,
        "Shared with me",
        "Someone added you to an issue as a participant.",
        personal=True,
        default_channel=Channel.BOTH.value,
    ),
    NotificationKindSpec(
        NotificationType.APPROVAL.value,
        "Approvals",
        "An approval is waiting on you, or one you asked for was decided.",
        personal=True,
        default_channel=Channel.BOTH.value,
    ),
    NotificationKindSpec(
        NotificationType.AUTOMATION.value,
        "Automation messages",
        "An automation rule was written to tell you something.",
        personal=True,
        default_channel=Channel.INBOX.value,
    ),
    NotificationKindSpec(
        NotificationType.COMMENTED.value,
        "Comments",
        "Someone commented on an issue or a page.",
        personal=False,
        default_channel=Channel.BOTH.value,
    ),
    NotificationKindSpec(
        NotificationType.STATE_CHANGED.value,
        "State changes",
        "An issue moved from one workflow state to another.",
        personal=False,
        default_channel=Channel.INBOX.value,
    ),
    NotificationKindSpec(
        NotificationType.UPDATED.value,
        "Any other edit",
        "A field changed — priority, labels, estimate, a custom field.",
        personal=False,
        default_channel=Channel.OFF.value,
    ),
    NotificationKindSpec(
        NotificationType.CREATED.value,
        "New issues",
        "An issue was filed.",
        personal=False,
        default_channel=Channel.OFF.value,
    ),
    NotificationKindSpec(
        NotificationType.SLA_BREACH.value,
        "SLA breaches",
        "An SLA clock ran out.",
        personal=False,
        default_channel=Channel.INBOX.value,
    ),
    NotificationKindSpec(
        NotificationType.SLA_DUE_SOON.value,
        "SLA warnings",
        "An SLA clock is about to run out.",
        personal=False,
        default_channel=Channel.INBOX.value,
    ),
    NotificationKindSpec(
        NotificationType.PAGE_CREATED.value,
        "New pages",
        "A page was created in a space.",
        personal=False,
        default_channel=Channel.OFF.value,
    ),
    NotificationKindSpec(
        NotificationType.PAGE_UPDATED.value,
        "Page edits",
        "A wiki page's content was edited.",
        personal=False,
        default_channel=Channel.INBOX.value,
    ),
)


def all_specs() -> tuple[NotificationKindSpec, ...]:
    """Every kind, core first, then what plugins registered (RADD-1326). The
    core tuple is the floor, so a caller that runs before plugins load still
    sees notify's own kinds."""
    core = {spec.key: spec for spec in NOTIFICATION_KINDS}
    extra = tuple(spec for key, spec in registries.notification_kinds.items() if key not in core)
    return NOTIFICATION_KINDS + extra


def spec_for(kind: str) -> NotificationKindSpec | None:
    key = str(kind)
    return next((spec for spec in all_specs() if spec.key == key), None)


def contributed_for(event_type: str) -> tuple[NotificationKindSpec, ...]:
    """Every contributed kind answering an event, including core events."""
    return tuple(spec for spec in registries.notification_kinds.values()
                 if event_type in spec.events and spec.recipients is not None)


def contributed_events() -> frozenset[str]:
    return frozenset(
        event for spec in registries.notification_kinds.values() if spec.recipients is not None for event in spec.events
    )


def is_personal(kind: str) -> bool:
    """Unknown kinds count as personal — the conservative answer: it still
    reaches the person the producer addressed."""
    spec = spec_for(kind)
    return True if spec is None else spec.personal


def every_kind() -> tuple[str, ...]:
    return tuple(spec.key for spec in all_specs())
