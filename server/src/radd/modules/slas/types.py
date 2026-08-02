from enum import StrEnum


class SlaEvent(StrEnum):
    POLICY_CREATED = "sla_policy.created"
    POLICY_UPDATED = "sla_policy.updated"
    POLICY_DELETED = "sla_policy.deleted"
    # Emitted with entity_type=item so it lands in the item's history feed.
    BREACHED = "sla.breached"
    # Spec 69: pre-breach warning — fired ONCE per item/policy/kind when the
    # remaining active time drops to the policy's warning_minutes. Payload
    # mirrors BREACHED plus remaining_seconds. Same entity_type=item.
    DUE_SOON = "sla.due_soon"


class SlaEntity(StrEnum):
    POLICY = "sla_policy"


class SlaKind(StrEnum):
    """The two timers a policy can set targets for."""

    RESPONSE = "response"
    RESOLUTION = "resolution"
