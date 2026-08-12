"""What the automation AI-classifier node sends the model (spec 116).

Pure/in-memory — `build_context` takes a session only to pass to the item and
comment services, so stubs cover the shaping rules, which is where the decisions
are.

The rule these pin: the budget is spent on WHOLE ITEMS. An earlier version capped
descriptions at 600 characters and comments at five per item — numbers invented
in the module with a rationale written afterwards. Truncating a description
mid-sentence can remove the exact line that decides "bug or feature", and no
budget arithmetic makes that a good trade.
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
    """`include` is an OBJECT of booleans, and the generated form rendered it as
    a free-text input until RADD-1064 — so instances hold nodes whose `include`
    is a string somebody typed. `"…".get(…)` is an AttributeError raised inside
    `_ask`, which `ai.validate` catches as "the provider is unavailable": a check
    that runs forever, checks nothing, and blames the model server.

    The write path does not refuse it either — `_check_node_schema` is
    deliberately shallow (required keys and enums), and tightening it would 422
    the very save that repairs the node. So the reading is what forgives it.
    """
    assert ContextOptions.from_params({"include": "{{title}}"}) == ContextOptions()
    assert ContextOptions.from_params({"include": ["fields"]}) == ContextOptions()
    assert ContextOptions.from_params({}) == ContextOptions()
    # A real mapping is still honoured, including the falsy half.
    assert ContextOptions.from_params({"include": {"description": False, "comments": True}}) == (
        ContextOptions(fields=True, description=False, comments=True, worklogs=False)
    )
