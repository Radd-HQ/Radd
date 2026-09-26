"""RADD-1324: `{{root.field}}` vocabularies come from a registry, and contributed
nodes render them.

`page` and `comment` moved out of the engine to the modules that own those
payloads; a plugin adds a root the same way — registered here directly into the
kernel registry, which is what `RaddPlugin.token_providers` does at load.
"""

import uuid

import pytest
from sqlalchemy import select

from radd.config import settings
from radd.kernel import TokenProviderSpec, load_plugins
from radd.kernel.registry import registries
from radd.modules.auth.models import User
from radd.modules.automations import engine, service as automations, templating
from radd.modules.automations.conditions import EventFacts
from radd.modules.automations.schemas import RuleCreate


@pytest.fixture
def widget_tokens():
    load_plugins(settings.modules)
    spec = TokenProviderSpec(
        root="widget",
        tokens=(("name", "The widget's name."),),
        resolve=lambda field, payload: (payload.get("widget") or {}).get(field),
    )
    registries.token_providers["widget"] = spec
    yield spec
    registries.token_providers.pop("widget", None)


def _facts(**payload) -> EventFacts:
    return EventFacts(event_type="widget.poked", actor_id=None, actor_email=None, actor_name=None, payload=payload)


def test_a_plugins_token_root_renders_is_documented_and_is_reserved(widget_tokens):
    assert templating.Renderer(_facts(widget={"name": "Gizmo"}))("Poked {{widget.name}}") == "Poked Gizmo"
    # Nothing to say → verbatim, like any unknown token.
    assert templating.Renderer(_facts())("{{widget.name}}") == "{{widget.name}}"
    assert "{{widget.name}}" in {info.token for info in templating.all_tokens()}
    # A node may not be NAMED `widget` — it would shadow the root.
    assert "widget" in templating.reserved_roots()


def test_page_and_comment_are_providers_not_engine_code():
    load_plugins(settings.modules)
    assert {"page", "comment"} <= set(registries.token_providers)
    facts = _facts(page={"title": "Runbook", "number": 7, "space": {"slug": "ops"}}, visibility="internal")
    assert templating.Renderer(facts)("{{page.title}} in {{page.space}}") == "Runbook in ops"
    assert templating.Renderer(facts)("{{comment.visibility}}") == "internal"


async def test_a_page_comment_renders_the_pages_title_on_a_manual_page_run(db):
    """`{{page.title}}` used to be posted verbatim by the page.comment node — it
    saved cleanly (the write check accepts reserved roots) and never rendered."""
    from radd.modules.comments.models import Comment
    from radd.modules.pages import service as pages, spaces
    from radd.modules.pages.schemas import PageCreate, PageSpaceCreate

    admin = User(email=f"tok-{uuid.uuid4().hex[:8]}@example.com", name="Tok", instance_role="admin")
    db.add(admin)
    await db.flush()
    slug = f"t{uuid.uuid4().hex[:6]}"
    space = await spaces.create_space(db, PageSpaceCreate(name=f"Space {slug}", slug=slug), admin.id)
    page = await pages.create_page(db, PageCreate(space_id=space.id, title="Runbook", body="x"), admin.id)
    rule = await automations.create_rule(db, RuleCreate.model_validate({
        "name": "stamp",
        "nodes": [
            {"id": "trg", "kind": "trigger", "type": "trigger.event", "params": {"event": "manual"}},
            {"id": "act", "kind": "action", "type": "page.comment", "params": {"body": "Reviewed {{page.title}}."}},
        ],
        "edges": [{"source": "trg", "port": "out", "target": "act"}],
    }), admin.id)
    await engine.run_manual(db, rule, page.id, start_node_id="trg", subject="page")
    await db.flush()
    bodies = [c.body for c in (await db.execute(select(Comment).where(Comment.entity_id == page.id))).scalars()]
    assert bodies == ["Reviewed Runbook."]
