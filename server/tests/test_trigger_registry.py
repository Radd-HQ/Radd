"""The trigger catalog derived from the event-type registry must equal
`_trigger_catalog_snapshot.json`; a changed `event_types` manifest fails here, not
silently in the UI. Update the snapshot deliberately.
"""

import json
from pathlib import Path

from radd.config import settings
from radd.kernel import load_plugins, registries

_SNAPSHOT = json.loads((Path(__file__).parent / "_trigger_catalog_snapshot.json").read_text())


def _current_triggers() -> dict[str, dict]:
    load_plugins(settings.modules)
    return {
        et: {
            "label": s.label,
            "group": s.group,
            "item_scoped": s.item_scoped,
            "has_changes": s.has_changes,
        }
        for et, s in registries.triggers().items()
    }


def test_trigger_registry_reproduces_the_catalog_exactly():
    current = _current_triggers()
    assert set(current) == set(_SNAPSHOT), (
        f"missing: {set(_SNAPSHOT) - set(current)}; extra: {set(current) - set(_SNAPSHOT)}"
    )
    for et, expected in _SNAPSHOT.items():
        assert current[et] == expected, f"{et}: {current[et]} != {expected}"


def test_trigger_count_is_112():
    assert len(_current_triggers()) == 112
