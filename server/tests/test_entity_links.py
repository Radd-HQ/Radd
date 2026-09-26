"""Owner navigation contracts preserve pre-migration destinations and live lifetimes."""
import importlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from radd.kernel import EntityRefSpec, EntitySpec, EventTypeSpec, KernelRegistries, RaddPlugin
from radd.sdk import EntityLinkSpec
from radd.kernel.entity_links import resolve_entity_link


def resolve(registry, kind='fixture', entity_id='id', refs=None, project=None):
    return resolve_entity_link(kind, entity_id, refs=refs or {}, project=project, registry=registry)



def declaring_plugin(name, *, entity_links, **kwargs):
    events = tuple(EventTypeSpec(link.entity_type+'.updated', 'Updated', 'Test', entity_type=link.entity_type) for link in entity_links)
    return RaddPlugin(name=name, entity_links=entity_links, event_types=events, **kwargs)

def test_every_former_host_mapping_is_owned_and_resolves_to_the_same_destination():
    expected = json.loads((Path(__file__).parent/'fixtures/audit-entity-destinations.json').read_text())
    registry = KernelRegistries()
    for owner in sorted({row['owner'] for row in expected}):
        registry.register_plugin(importlib.import_module(f'radd.modules.{owner}').plugin)
    for row in expected:
        destination = resolve(registry, row['entity_type'], refs={'item': {'key': 'TEST-7'}, 'page': {'number': 123}}, project={'key': 'TEST'})
        assert destination is not None, row
        assert (destination.owner, destination.url) == (row['owner'], row['url'])
    assert len(expected) == 46


def test_missing_context_falls_back_only_when_the_owner_declares_it():
    from radd.modules.pages import plugin as pages
    from radd.modules.settings import plugin as settings
    from radd.modules.releases import plugin as releases
    registry = KernelRegistries()
    for plugin in [pages, settings, releases]:
        registry.register_plugin(plugin)
    assert resolve(registry, 'page', refs={'page': {'id': 'saved-uuid'}}).url == '/pages?pageId=saved-uuid'
    assert resolve(registry, 'page', refs={'page': {'number': 123, 'id': 'saved-uuid', 'slug': 'old-name'}}).url == '/pages?pageId=123'
    assert resolve(registry, 'page') is None
    assert resolve(registry, 'release') is None
    assert resolve(registry, 'scoped_setting').url == '/settings/general'
    assert resolve(registry, 'scoped_setting', project={'key': 'A/B ?'}).url == '/p/A%2FB%20%3F/settings/general'


def test_registration_is_atomic_replacement_removes_old_keys_and_late_cleanup_is_harmless():
    registry = KernelRegistries()
    owner = declaring_plugin(name='fixture', id='org.fixture', entity_links=(EntityLinkSpec('fixture', ('/old/{id}',)),))
    registry.register_plugin(owner)
    registry.register_plugin(owner)
    assert len(registry.entity_links) == 1
    conflicting = declaring_plugin(name='other', entity_links=(EntityLinkSpec('other', ('/other',)), EntityLinkSpec('fixture', ('/stolen',))))
    with pytest.raises(ValueError, match='already belongs'):
        registry.register_plugin(conflicting)
    assert set(registry.plugins) == {'org.fixture'}
    assert set(registry.entity_links) == {'fixture'}
    replacement = replace(owner, entity_links=(EntityLinkSpec('new', ('/new',)),), event_types=(EventTypeSpec('new.updated', 'Updated', 'Test', entity_type='new'),))
    registry.register_plugin(replacement)
    registry.unregister_plugin(owner)
    assert resolve(registry) is None
    assert resolve(registry, 'new').url == '/new'
    registry.unregister_plugin(replacement)
    assert not registry.entity_links and not registry.entity_link_owners
    registry.register_plugin(owner)
    assert resolve(registry).url == '/old/id'
    registry.clear()
    assert not registry.entity_links and not registry.entity_link_owners


def test_derived_entity_and_ref_destinations_use_current_declarations_not_payload_urls():
    registry = KernelRegistries()
    plugin = RaddPlugin(name='extension', entities=(EntitySpec(key='note', table='notes', label='Note', plural='Notes', url='/notes#note-{id}'),),
        entity_refs=(EntityRefSpec('reference', lambda *args: None, url='/refs/{id}'),))
    registry.register_plugin(plugin)
    assert resolve(registry, 'note', entity_id='a/b?c#d').url == '/notes#note-a%2Fb%3Fc%23d'
    assert resolve(registry, 'reference', refs={'reference': {'url': '//wrong.example'}}).url == '/refs/id'
    registry.unregister_plugin(plugin)
    assert resolve(registry, 'note', refs={'note': {'url': '/stale'}}) is None


@pytest.mark.parametrize('template', ['//outside.test/path', 'https://outside.test', '/\\outside', '/\npath', '/{missing}', '/{id!r}', '/{id:>3}', '/{refs[x]}'])
def test_invalid_templates_fail_at_declaration(template):
    with pytest.raises(ValueError):
        EntityLinkSpec('fixture', (template,))


def test_duplicate_types_fail_before_registry_mutation():
    registry = KernelRegistries()
    with pytest.raises(ValueError, match='duplicate'):
        registry.register_plugin(declaring_plugin(name='fixture', entity_links=(EntityLinkSpec('fixture', ('/one',)), EntityLinkSpec('fixture', ('/two',)))))
    assert not registry.plugins


def test_links_cannot_silently_claim_an_entity_the_plugin_does_not_declare():
    registry = KernelRegistries()
    with pytest.raises(ValueError, match='declared entity types'):
        registry.register_plugin(RaddPlugin(name='unrelated', entity_links=(EntityLinkSpec('fixture', ('/wrong',)),)))
    assert not registry.plugins and not registry.entity_links
