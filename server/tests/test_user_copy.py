"""RADD-1289: text written for the people using Radd names no spec or ticket.

The settings editor, the Plugins page, the roles matrix and the automation/audit
catalogs render these registry strings verbatim. "(spec 121)" or "RADD-982"
there tells a team lead nothing and tells them the page was written for the
codebase. Internal references belong in comments and commit messages.

Pure/in-memory — reads the registry conftest's autouse fixture loads.
"""

import re

from radd.kernel import registries

INTERNAL_REFERENCE = re.compile(r"\b(?:[Ss]pecs? \d+|RADD-\d+)\b")


def _offenders(pairs):
    return sorted(f"{where}: {text!r}" for where, text in pairs if text and INTERNAL_REFERENCE.search(text))


def test_settings_labels_and_descriptions_name_no_spec_or_ticket():
    pairs = []
    for key, spec in registries.settings.items():
        pairs += [(f"setting {key}.label", spec.label), (f"setting {key}.description", spec.description)]
    assert not _offenders(pairs), "\n".join(_offenders(pairs))


def test_plugin_descriptions_name_no_spec_or_ticket():
    pairs = [(f"plugin {name}", plugin.description) for name, plugin in registries.plugins.items()]
    assert not _offenders(pairs), "\n".join(_offenders(pairs))


def test_permission_and_event_copy_names_no_spec_or_ticket():
    pairs = [(f"permission {key}", spec.description) for key, spec in registries.permissions.items()]
    pairs += [(f"event {key}", spec.label) for key, spec in registries.event_types.items()]
    pairs += [(f"event {key}.description", getattr(spec, "description", "")) for key, spec in registries.event_types.items()]
    assert not _offenders(pairs), "\n".join(_offenders(pairs))
