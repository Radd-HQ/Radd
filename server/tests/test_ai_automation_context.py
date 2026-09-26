"""What the automation AI-classifier node sends the model (spec 116). Pure: stubs
cover the shaping rules. The budget is spent on WHOLE ITEMS — truncating a
description mid-sentence can remove the exact line that decides "bug or feature".
"""

from dataclasses import dataclass, field
from typing import Any

import pytest

from radd.config import settings
from radd.modules.ai.automation_context import ContextOptions, build_context


@dataclass
class _State:
    name: str = "Todo"


@dataclass
class _Person:
    name: str = "Ada"


@dataclass
class _Read:
    key: str
    title: str
    description: str = ""
    kind: str = "issue"
    priority: str = "normal"
    state: _State = field(default_factory=_State)
    assignee: _Person | None = None
    labels: list[str] = field(default_factory=list)
    custom_fields: dict[str, Any] = field(default_factory=dict)
    project_id: str = "p"


@dataclass
class _Comment:
    body: str
    author: _Person = field(default_factory=_Person)


class _Items:
    def __init__(self, reads: dict[Any, _Read]):
        self._reads = reads

    async def get_item(self, _session, item_id, _actor):
        return self._reads[item_id]


class _Comments:
    def __init__(self, by_item: dict[Any, list[_Comment]]):
        self._by_item = by_item

    async def list_comments(self, _session, item_id, _actor):
        return self._by_item.get(item_id, [])


@pytest.fixture
def stub(monkeypatch):
    """Patch the service seams `build_context` imports lazily."""

    def install(reads, comments=None):
        import radd.modules.comments.service as comments_service
        import radd.modules.items.service as items_service

        items = _Items(reads)
        monkeypatch.setattr(items_service, "get_item", items.get_item, raising=False)
        stub_comments = _Comments(comments or {})
        monkeypatch.setattr(
            comments_service, "list_comments", stub_comments.list_comments, raising=False
        )

    return install


async def test_a_long_description_is_sent_whole(stub):
    """The decisive sentence is often the last one. Anything that clips a
    description can remove exactly the evidence the question is about."""
    body = "A. " * 5_000  # 15k characters, far past any per-field cap
    stub({1: _Read(key="TD-1", title="t", description=body)})

    text = await build_context(None, (1,), None, ContextOptions())

    assert body.strip() in text
    assert "…" not in text  # nothing was elided mid-field


async def test_every_comment_is_sent_when_comments_are_included(stub):
    """Not "the five most recent" — a classification about tone or resolution
    reads the whole thread, and picking a number here was guesswork."""
    comments = [_Comment(body=f"comment {n}") for n in range(20)]
    stub({1: _Read(key="TD-1", title="t")}, {1: comments})

    text = await build_context(None, (1,), None, ContextOptions(comments=True))

    for comment in comments:
        assert comment.body in text


async def test_the_budget_drops_whole_items_and_says_how_many(monkeypatch, stub):
    """When the budget runs out the REMAINING ITEMS are omitted, and the prompt
    says so — a model answering about a sample must know it is a sample."""
    monkeypatch.setattr(settings, "ai_automation_context_chars", 400)
    big = "x" * 300
    stub({n: _Read(key=f"TD-{n}", title="t", description=big) for n in range(1, 6)})

    text = await build_context(None, (1, 2, 3, 4, 5), None, ContextOptions())

    assert "TD-1" in text  # the first item is always included
    assert "TD-5" not in text  # the budget stopped before it
    assert "not shown" in text and "budget" in text
    # Whatever WAS included is intact, not clipped.
    assert big in text


async def test_one_oversized_item_still_produces_a_prompt(monkeypatch, stub):
    """A single item larger than the whole budget must not yield an empty digest —
    one item over budget is a better prompt than nothing at all."""
    monkeypatch.setattr(settings, "ai_automation_context_chars", 50)
    stub({1: _Read(key="TD-1", title="t", description="y" * 5_000)})

    text = await build_context(None, (1,), None, ContextOptions())

    assert "TD-1" in text
    assert "yyyy" in text


async def test_sections_are_omitted_when_not_requested(stub):
    """Comments and time are OFF by default: sending them to a provider when the
    question is about titles is a privacy cost with no benefit."""
    stub({1: _Read(key="TD-1", title="t", description="d")}, {1: [_Comment(body="secret")]})

    text = await build_context(None, (1,), None, ContextOptions(comments=False))

    assert "secret" not in text


async def test_no_items_says_so_rather_than_sending_an_empty_prompt(stub):
    stub({})
    assert "No items matched" in await build_context(None, (), None, ContextOptions())


# --- what a stored param actually holds (RADD-1064) ---------------------------


def test_a_choice_that_is_not_a_mapping_falls_back_to_the_defaults():
    """Stored nodes may hold `include` as a typed-in STRING (the form rendered it as
    free text before RADD-1064); `.get` on it raised inside `_ask`, which `ai.validate`
    reports as "provider unavailable". The save path is deliberately shallow (a
    stricter check would 422 the repairing save), so the reading forgives it."""
    assert ContextOptions.from_params({"include": "{{title}}"}) == ContextOptions()
    assert ContextOptions.from_params({"include": ["fields"]}) == ContextOptions()
    assert ContextOptions.from_params({}) == ContextOptions()
    # A real mapping is still honoured, including the falsy half.
    assert ContextOptions.from_params({"include": {"description": False, "comments": True}}) == (
        ContextOptions(fields=True, description=False, comments=True, worklogs=False)
    )


async def test_logged_time_carries_the_items_total():
    """RADD-1418: the "Logged time" section passed a UUID where `item_summary`
    takes a project and read a field that does not exist, so it always said
    "not tracked". It is now the summarize time digest."""
    import uuid
    from datetime import date

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from radd.kernel import load_plugins
    from radd.modules.auth.models import User
    from radd.modules.auth.types import InstanceRole
    from radd.modules.items import service as items_service
    from radd.modules.items.schemas import ItemCreate
    from radd.modules.projects import service as projects_service
    from radd.modules.projects.schemas import ProjectCreate
    from radd.modules.timelogging import enablement
    from radd.modules.timelogging.models import Worklog

    load_plugins(settings.modules)
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        actor = User(
            email=f"ctx-{uuid.uuid4().hex[:8]}@example.com", name="Ada",
            instance_role=InstanceRole.ADMIN.value,
        )
        session.add(actor)
        await session.flush()
        project = await projects_service.create_project(
            session, ProjectCreate(key=f"CX{uuid.uuid4().hex[:4].upper()}", name="Ctx")
        )
        await enablement.set_enabled(session, project.id, True)
        item = await items_service.create_item(
            session, ItemCreate(project_id=project.id, title="Timed"), actor
        )
        session.add(Worklog(
            item_id=item.id, author_id=actor.id, worked_on=date(2026, 9, 1),
            time_spent_seconds=5400,
        ))
        await session.flush()

        prompt = await build_context(
            session, (item.id,), actor, ContextOptions(worklogs=True)
        )
        await session.rollback()
    await engine.dispose()
    assert "Total logged: 1h 30m" in prompt, prompt
