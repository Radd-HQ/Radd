"""The matrix's ROWS: every notification kind, labelled and classified (spec 118).

One ordered constant, served to the SPA by the preferences endpoint. The panel
it replaces hardcoded its own label map in TypeScript, so adding a kind meant
editing the enum, the settings panel and the proof's row count — three places
that could disagree, and one of them in a different language. A kind is now a
vocabulary entry: add it here and it has a row, a label and a default.

**Personal vs ambient is the load-bearing distinction.** A personal kind is
structurally addressed AT someone — you were assigned it, named in it, asked to
approve it, added to it, or an automation rule was written to tell YOU. There is
no relationship to resolve, because the event picked the recipient; so a
personal kind resolves through the `own` column alone and the settings page
greys the other two. An ambient kind reaches you because of how you are
connected to the subject, and that connection is exactly what the matrix's
columns enumerate.

Getting that wrong is not cosmetic. `approval` goes to eligible approvers, who
are frequently neither the assignee nor a watcher; resolving it through a
relationship scope would have handed them `off` and silently ended approvals.
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

#: Core kinds that resolve through `own` alone (see the module docstring).
PERSONAL_KINDS: frozenset[str] = frozenset(spec.key for spec in NOTIFICATION_KINDS if spec.personal)

#: The kinds spec 118 ADDED. They exist for subscribers, so they are `off`
#: everywhere by default — an instance that never opens the settings page must
#: not start receiving a class of notification it has never had.
SUBSCRIPTION_ONLY_KINDS: frozenset[str] = frozenset(
    {NotificationType.CREATED.value, NotificationType.UPDATED.value, NotificationType.PAGE_CREATED.value}
)


def all_specs() -> tuple[NotificationKindSpec, ...]:
    """Every kind, core first, then what plugins contributed (RADD-1326).

    Read from the kernel registry, so a plugin's kind has a matrix row, a label
    and a default without an edit here. The core tuple is the floor: a caller
    that runs before plugins load (a unit test, an import-time default) still
    sees the kinds notify itself owns.
    """
    core = {spec.key: spec for spec in NOTIFICATION_KINDS}
    extra = tuple(spec for key, spec in registries.notification_kinds.items() if key not in core)
    return NOTIFICATION_KINDS + extra


def spec_for(kind: str) -> NotificationKindSpec | None:
    key = str(kind)
    return next((spec for spec in all_specs() if spec.key == key), None)


def contributed_for(event_type: str) -> NotificationKindSpec | None:
    """The contributed kind that answers this event, if any."""
    for spec in registries.notification_kinds.values():
        if event_type in spec.events and spec.recipients is not None:
            return spec
    return None


def contributed_events() -> frozenset[str]:
    return frozenset(
        event for spec in registries.notification_kinds.values() if spec.recipients is not None for event in spec.events
    )


def is_personal(kind: str) -> bool:
    """Unknown kinds count as personal — the conservative answer.

    A kind with no vocabulary entry is a programming error, and treating it as
    own-directed means it still reaches the person the producer addressed rather
    than vanishing into a relationship that was never computed.
    """
    spec = spec_for(kind)
    return True if spec is None else spec.personal


def every_kind() -> tuple[str, ...]:
    return tuple(spec.key for spec in all_specs())
