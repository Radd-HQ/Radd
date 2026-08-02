# Copyright 2026 the Radd authors
# SPDX-License-Identifier: Apache-2.0
"""Example plugin: on `sla.breached`, label the item and leave a comment.

Drop this file into your runner's plugins dir. The breach event payload carries
item_id, item_key, policy_name, kind (response|resolution) and due_at — see the
tracker's slas module.
"""

from radd_sdk import Event, RaddClient

BREACH_LABEL = "sla-breached"


def register(reg) -> None:
    reg.on("sla.breached", on_breach)


def on_breach(client: RaddClient, event: Event) -> None:
    item_id = event.payload["item_id"]
    item = client.get(f"/items/{item_id}")
    labels = list(item["labels"])
    if BREACH_LABEL not in labels:
        client.update_item(item_id, labels=[*labels, BREACH_LABEL])
    policy = event.payload.get("policy_name", "?")
    kind = event.payload.get("kind", "?")
    due_at = event.payload.get("due_at")
    client.add_comment(
        item_id,
        f"SLA **{policy}** ({kind}) breached" + (f" — was due {due_at}." if due_at else "."),
    )
