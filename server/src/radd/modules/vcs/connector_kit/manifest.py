"""What a connector's manifest contributes, derived from its spec (RADD-1435), and the
read side: the connectors loaded NOW."""

from radd.kernel import EntityLinkSpec, EventTypeSpec, IntegrationSpec
from radd.kernel import sockets

from ..types import VcsSocket
from .spec import ConnectorSpec

#: Where the audit log links a connection or a repository to.
SETTINGS_PATH = "/settings/vcs"


def admin_event_types(spec: ConnectorSpec) -> tuple[EventTypeSpec, ...]:
    """Spec 123: connection + repository administration, audited with a diff (tokens
    and secrets appear only as "changed"). Not triggers."""
    title, noun = spec.wording.title, spec.wording.repo_noun
    events, entities = spec.events, spec.entities
    rows = (
        (events.CONNECTION_CREATED, f"{title} connection created", entities.CONNECTION),
        (events.CONNECTION_UPDATED, f"{title} connection updated", entities.CONNECTION),
        (events.CONNECTION_DELETED, f"{title} connection deleted", entities.CONNECTION),
        (events.REPO_CREATED, f"{title} {noun} added", entities.REPO),
        (events.REPO_UPDATED, f"{title} {noun} updated", entities.REPO),
        (events.REPO_DELETED, f"{title} {noun} removed", entities.REPO),
    )
    return tuple(
        EventTypeSpec(
            event_type, label, "Admin",
            has_changes=event_type is events.CONNECTION_UPDATED or event_type is events.REPO_UPDATED,
            trigger=False, entity_type=entity.value,
        )
        for event_type, label, entity in rows
    )


def entity_links(spec: ConnectorSpec) -> tuple[EntityLinkSpec, ...]:
    target = (f"{SETTINGS_PATH}?host={spec.provider.value}",)
    return tuple(EntityLinkSpec(entity.value, target) for entity in (spec.entities.CONNECTION, spec.entities.REPO))


def integration(spec: ConnectorSpec) -> IntegrationSpec:
    """The connector's spec on the vcs socket — what makes its tab appear."""
    return IntegrationSpec(VcsSocket.CONNECTOR, spec.provider.value, impl=spec)


def loaded_connectors() -> list[ConnectorSpec]:
    """Every connector whose plugin is loaded now, in tab order."""
    specs = sockets.providers(VcsSocket.CONNECTOR).values()
    return sorted(specs, key=lambda spec: (spec.wording.order, spec.wording.title))
