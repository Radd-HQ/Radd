"""Field-level change diffs for item history (audit / History tab).

`update_item`/link changes emit `item.updated` with a full item snapshot (stream
consumers are trusted). This module additionally computes a human-readable
`changes` list — `[{field, from, to, …}]` with display values resolved AT WRITE
TIME (state/assignee/cycle names, custom-field labels) so the record is
self-contained and stays accurate even if a state/user is later renamed or
deleted. The History endpoint renders these verbatim; webhooks/automations get
the same richer diff for free.

Pure over two `ItemRead`s — no I/O — so it's trivially testable.
"""

from collections.abc import Sequence

from .enums import ItemLinkType
from .schemas import ItemRead


def _date(value: object) -> str | None:
    """A date/datetime -> ISO string; None stays None (JSON-safe for the payload)."""
    return value.isoformat() if value is not None else None  # type: ignore[union-attr]


def _link_keys(read: ItemRead) -> dict[tuple[str, str], dict]:
    """Every user-managed dependency edge on the item, keyed by (link_type, far-item
    key). `mentions` edges are auto-derived from item text (spec 52) — excluded so
    editing a description doesn't spam the History feed with link changes."""
    edges: dict[tuple[str, str], dict] = {}
    for edge in [*read.links.outgoing, *read.links.incoming]:
        if edge.link_type == ItemLinkType.MENTIONS:
            continue
        edges[(str(edge.link_type), edge.item.key)] = {
            "link_type": str(edge.link_type),
            "key": edge.item.key,
            "title": edge.item.title,
        }
    return edges


def diff_item_reads(
    before: ItemRead, after: ItemRead, *, field_names: dict[str, str]
) -> list[dict]:
    """Ordered, JSON-serializable field changes between two item snapshots.

    `field_names` maps a custom-field key to its display name (from the registry).
    Description diffs record only that it changed (no potentially-large content).
    """
    changes: list[dict] = []

    def scalar(field: str, old: object, new: object) -> None:
        if old != new:
            changes.append({"field": field, "from": old, "to": new})

    scalar("title", before.title, after.title)
    if before.description != after.description:
        changes.append({"field": "description"})
    scalar("state", before.state.name, after.state.name)
    scalar("priority", str(before.priority), str(after.priority))
    scalar("archived", before.archived_at is not None, after.archived_at is not None)
    scalar(
        "assignee",
        before.assignee.name if before.assignee else None,
        after.assignee.name if after.assignee else None,
    )
    scalar(
        "reporter",
        before.reporter.name if before.reporter else None,
        after.reporter.name if after.reporter else None,
    )
    scalar(
        "team",
        before.team.name if before.team else None,
        after.team.name if after.team else None,
    )
    scalar(
        "parent",
        before.parent.key if before.parent else None,
        after.parent.key if after.parent else None,
    )
    scalar(
        "cycle",
        before.cycle.name if before.cycle else None,
        after.cycle.name if after.cycle else None,
    )
    scalar(
        "release",
        before.release.version if before.release else None,
        after.release.version if after.release else None,
    )
    scalar("start_date", _date(before.start_date), _date(after.start_date))
    scalar("target_date", _date(before.target_date), _date(after.target_date))
    scalar("flagged", before.flagged, after.flagged)
    scalar("points", before.estimate_points, after.estimate_points)

    old_labels, new_labels = set(before.labels), set(after.labels)
    if old_labels != new_labels:
        changes.append(
            {
                "field": "labels",
                "added": sorted(new_labels - old_labels),
                "removed": sorted(old_labels - new_labels),
            }
        )

    for key in sorted(set(before.custom_fields) | set(after.custom_fields)):
        old_value = before.custom_fields.get(key)
        new_value = after.custom_fields.get(key)
        if old_value != new_value:
            changes.append(
                {
                    "field": "custom_field",
                    "key": key,
                    "name": field_names.get(key, key),
                    "from": old_value,
                    "to": new_value,
                }
            )

    old_links, new_links = _link_keys(before), _link_keys(after)
    if old_links.keys() != new_links.keys():
        added = [value for key, value in new_links.items() if key not in old_links]
        removed = [value for key, value in old_links.items() if key not in new_links]
        changes.append({"field": "links", "added": added, "removed": removed})

    return changes


def field_name_map(definitions: Sequence[object]) -> dict[str, str]:
    """Custom-field key -> display name, for labelling `custom_field` changes."""
    return {d.key: d.name for d in definitions}  # type: ignore[attr-defined]
