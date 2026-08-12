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

from dataclasses import dataclass

from .types import NotificationType


@dataclass(frozen=True)
class NotificationKind:
    """One row of the matrix — the wire value, how to name it, and how it resolves."""

    kind: NotificationType
    label: str
    description: str
    #: Addressed AT a person by the event itself: resolves through `own` only.
    personal: bool


#: Every kind, in the order the settings page lists them: personally-directed
#: first (the ones nobody should have to hunt for), then the ambient stream.
NOTIFICATION_KINDS: tuple[NotificationKind, ...] = (
    NotificationKind(
        NotificationType.ASSIGNED,
        "Assigned to me",
        "An issue was assigned to you.",
        personal=True,
    ),
    NotificationKind(
        NotificationType.MENTIONED,
        "Mentions",
        "Someone @-named you in a description or a comment.",
        personal=True,
    ),
    NotificationKind(
        NotificationType.PARTICIPANT_ADDED,
        "Shared with me",
        "Someone added you to an issue as a participant.",
        personal=True,
    ),
    NotificationKind(
        NotificationType.APPROVAL,
        "Approvals",
        "An approval is waiting on you, or one you asked for was decided.",
        personal=True,
    ),
    NotificationKind(
        NotificationType.AUTOMATION,
        "Automation messages",
        "An automation rule was written to tell you something.",
        personal=True,
    ),
    NotificationKind(
        NotificationType.COMMENTED,
        "Comments",
        "Someone commented on an issue or a page.",
        personal=False,
    ),
    NotificationKind(
        NotificationType.STATE_CHANGED,
        "State changes",
        "An issue moved from one workflow state to another.",
        personal=False,
    ),
    NotificationKind(
        NotificationType.UPDATED,
        "Any other edit",
        "A field changed — priority, labels, estimate, a custom field.",
        personal=False,
    ),
    NotificationKind(
        NotificationType.CREATED,
        "New issues",
        "An issue was filed.",
        personal=False,
    ),
    NotificationKind(
        NotificationType.SLA_BREACH,
        "SLA breaches",
        "An SLA clock ran out.",
        personal=False,
    ),
    NotificationKind(
        NotificationType.SLA_DUE_SOON,
        "SLA warnings",
        "An SLA clock is about to run out.",
        personal=False,
    ),
    NotificationKind(
        NotificationType.PAGE_CREATED,
        "New pages",
        "A page was created in a space.",
        personal=False,
    ),
    NotificationKind(
        NotificationType.PAGE_UPDATED,
        "Page edits",
        "A page changed.",
        personal=False,
    ),
)

#: Lookup by the enum member and by the wire string — a stored `channels` map is
#: JSON, so its keys arrive as strings.
KIND_SPECS: dict[NotificationType, NotificationKind] = {
    spec.kind: spec for spec in NOTIFICATION_KINDS
}

#: Kinds that resolve through `own` alone (see the module docstring).
PERSONAL_KINDS: frozenset[NotificationType] = frozenset(
    spec.kind for spec in NOTIFICATION_KINDS if spec.personal
)

#: The kinds spec 118 ADDED. They exist for subscribers, so they are `off`
#: everywhere by default — an instance that never opens the settings page must
#: not start receiving a class of notification it has never had.
SUBSCRIPTION_ONLY_KINDS: frozenset[NotificationType] = frozenset(
    {NotificationType.CREATED, NotificationType.UPDATED, NotificationType.PAGE_CREATED}
)


def is_personal(kind: NotificationType) -> bool:
    """Unknown kinds count as personal — the conservative answer.

    A kind with no vocabulary entry is a programming error, and treating it as
    own-directed means it still reaches the person the producer addressed rather
    than vanishing into a relationship that was never computed.
    """
    spec = KIND_SPECS.get(kind)
    return True if spec is None else spec.personal


def every_kind() -> tuple[NotificationType, ...]:
    return tuple(spec.kind for spec in NOTIFICATION_KINDS)
