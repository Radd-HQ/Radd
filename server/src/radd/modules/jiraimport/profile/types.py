"""What a cached snapshot contains — the profile the mapping step is built from.
Every vocabulary carries a USE COUNT from the snapshot itself, which makes
"unused" (hidden and ignored by default) a fact rather than a guess."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..types import InferredField


@dataclass
class VocabEntry:
    """One value of a Jira vocabulary, with how much of the snapshot uses it.

    `meta` carries whatever the mapping step needs to make a good suggestion —
    a status's `statusCategory`, a link type's inward/outward names, a version's
    release date.
    """

    value: str
    count: int = 0  # issues in the snapshot carrying it — 0 means hide + ignore
    meta: dict = field(default_factory=dict)

    @property
    def unused(self) -> bool:
        return self.count == 0


@dataclass
class PersonEntry:
    """One person the snapshot names, and where. Identity is Jira's stable
    username/key, NOT the email: Jira often exposes no address at all."""

    key: str  # Jira username / accountId — the stable identity
    display_name: str = ""
    email: str = ""  # only when Jira exposed one
    count: int = 0
    roles: set[str] = field(default_factory=set)  # assignee, reporter, comment, …

    @property
    def sorted_roles(self) -> list[str]:
        return sorted(self.roles)


@dataclass
class InboundProfile:
    """Everything the mapping step needs, derived from the cache in one pass."""

    fields: list[InferredField] = field(default_factory=list)
    issue_types: list[VocabEntry] = field(default_factory=list)
    statuses: list[VocabEntry] = field(default_factory=list)
    priorities: list[VocabEntry] = field(default_factory=list)
    link_types: list[VocabEntry] = field(default_factory=list)
    sprints: list[VocabEntry] = field(default_factory=list)
    versions: list[VocabEntry] = field(default_factory=list)
    components: list[VocabEntry] = field(default_factory=list)
    people: list[PersonEntry] = field(default_factory=list)
