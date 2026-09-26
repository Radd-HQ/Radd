"""Generic owner-supplied entity navigation, independent of Audit or feature pages."""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from string import Formatter
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

if TYPE_CHECKING:
    from .plugin import RaddPlugin
    from .registry import KernelRegistries
    from .specs import EntityLinkSpec

_FORMATTER = Formatter()
_FIELD = re.compile(r"(?:id|(?:refs|project)(?:\.[A-Za-z_][A-Za-z0-9_]*)+)$")


def _local_url(value: str) -> bool:
    return value.startswith('/') and not value.startswith('//') and not any(
        char == '\\' or ord(char) < 32 or ord(char) == 127 for char in value
    )


def validate_templates(entity_type: str, templates: tuple[str, ...]) -> None:
    if not entity_type or not isinstance(templates, tuple) or not templates:
        raise ValueError('entity links require a type and a nonempty tuple of templates')
    for template in templates:
        if not isinstance(template, str) or not _local_url(template):
            raise ValueError('entity link templates must be local absolute paths')
        for _literal, field, format_spec, conversion in _FORMATTER.parse(template):
            if field is not None and (not _FIELD.fullmatch(field) or format_spec or conversion):
                raise ValueError(f'unsupported entity link placeholder {field!r}')


def contributed_links(plugin: RaddPlugin) -> tuple[EntityLinkSpec, ...]:
    """Explicit links plus existing declarative/ref URLs, with one owner per key."""
    from .specs import EntityLinkSpec

    owned_types = (
        {entity.key for entity in plugin.entities}
        | {ref.entity_type for ref in plugin.entity_refs}
        | {event.entity_type or str(event.event_type).split('.')[0] for event in plugin.event_types}
        | {resource.key for resource in plugin.crud_resources}
    )
    if foreign := {link.entity_type for link in plugin.entity_links} - owned_types:
        raise ValueError(f'{plugin.name}: entity links must name its declared entity types: {sorted(foreign)}')
    links = {link.entity_type: link for link in plugin.entity_links}
    if len(links) != len(plugin.entity_links):
        raise ValueError(f'{plugin.name}: duplicate entity link types')
    for ref in plugin.entity_refs:
        if ref.url and ref.entity_type not in links:
            links[ref.entity_type] = EntityLinkSpec(ref.entity_type, (ref.url,))
    for entity in plugin.entities:
        if entity.url and entity.key not in links:
            links[entity.key] = EntityLinkSpec(entity.key, (entity.url,))
    return tuple(links.values())


@dataclass(frozen=True)
class EntityDestination:
    owner: str
    url: str


def resolve_entity_link(
    entity_type: str,
    entity_id: str,
    *,
    refs: Mapping[str, Any],
    project: Mapping[str, Any] | None = None,
    registry: KernelRegistries | None = None,
) -> EntityDestination | None:
    if registry is None:
        from .registry import registries
        registry = registries
    spec = registry.entity_links.get(entity_type)
    owner = registry.entity_link_owners.get(entity_type)
    if spec is None or owner is None:
        return None
    values = {'id': entity_id, 'refs': refs, 'project': project or {}}
    for template in spec.templates:
        pieces = []
        for literal, field, _format, _conversion in _FORMATTER.parse(template):
            pieces.append(literal)
            if field is None:
                continue
            value: Any = values
            for part in field.split('.'):
                value = value.get(part) if isinstance(value, Mapping) else None
            if isinstance(value, bool) or not isinstance(value, (str, int, float)) or value == '':
                break
            pieces.append(quote(str(value), safe=''))
        else:
            url = ''.join(pieces)
            if _local_url(url):
                return EntityDestination(owner=owner.name, url=url)
    return None
