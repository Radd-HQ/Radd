"""AI module pure cores (spec 46): the two provider payload builders, prompt
assembly over a stubbed registry, the lenient JSON extractors, the rerank
merge, and the NL->SLQ validation-retry decision. No network, no DB, no live
provider — the wired path is exercised in-process against a MockTransport.
"""

from dataclasses import dataclass
from datetime import datetime

import pytest

from radd.modules.ai import prompts, provider, service, similar
from radd.modules.ai.types import (
    ANTHROPIC_VERSION,
    NL_MAX_ATTEMPTS,
    OPENAI_TEMPLATE_KWARGS_KEY,
    OPENAI_THINKING_FLAG,
    AiWireShape,
    AiUpstreamError,
    NlOutcome,
    SimilarCandidate,
)
from radd.modules.items.schemas import HistoryActor, HistoryEntry

# --- provider payload/header builders ---


def test_openai_payload_shape():
    payload = provider.openai_payload("SYS", "USER", model="gpt-x", max_tokens=256)
    assert payload == {
        "model": "gpt-x",
        "max_tokens": 256,
        "messages": [
            {"role": "system", "content": "SYS"},
            {"role": "user", "content": "USER"},
        ],
    }


def test_anthropic_payload_shape():
    payload = provider.anthropic_payload("SYS", "USER", model="claude-x", max_tokens=512)
    # max_tokens is REQUIRED by /v1/messages; system rides top-level, not as a message.
    assert payload == {
        "model": "claude-x",
        "max_tokens": 512,
        "system": "SYS",
        "messages": [{"role": "user", "content": "USER"}],
    }


def test_provider_headers():
    assert provider.openai_headers("sk-1") == {"Authorization": "Bearer sk-1"}
    assert provider.anthropic_headers("ak-1") == {
        "x-api-key": "ak-1",
        "anthropic-version": ANTHROPIC_VERSION,
    }
    # Keyless self-hosted endpoints: NO auth header at all — an empty "Bearer "
    # is an illegal header value h11 refuses to send (found live against vLLM).
    assert provider.openai_headers("") == {}
    assert provider.anthropic_headers("") == {"anthropic-version": ANTHROPIC_VERSION}


def test_completions_url_defaults_and_override():
    assert (
        provider.completions_url(AiWireShape.OPENAI, "")
        == "https://api.openai.com/v1/chat/completions"
    )
    assert (
        provider.completions_url(AiWireShape.ANTHROPIC, "")
        == "https://api.anthropic.com/v1/messages"
    )
    # base_url override (LiteLLM/Ollama/vLLM); trailing slash tolerated.
    assert (
        provider.completions_url(AiWireShape.OPENAI, "http://localhost:11434/v1/")
        == "http://localhost:11434/v1/chat/completions"
    )


def test_extract_completion_text():
    assert (
        provider.extract_completion_text(
            AiWireShape.OPENAI, {"choices": [{"message": {"content": "hi"}}]}
        )
        == "hi"
    )
    assert (
        provider.extract_completion_text(
            AiWireShape.ANTHROPIC,
            {"content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]},
        )
        == "ab"
    )
    with pytest.raises(AiUpstreamError):
        provider.extract_completion_text(AiWireShape.OPENAI, {"unexpected": True})
    with pytest.raises(AiUpstreamError):
        provider.extract_completion_text(AiWireShape.ANTHROPIC, {"content": "not-a-list"})


# --- prompt assembly (stub registry) ---


@dataclass
class StubField:
    key: str
    name: str
    type: str
    options: list[str] | None = None
    ai_visible: bool = True


def test_nl_system_prompt_embeds_grammar_and_registry():
    prompt = prompts.nl_system_prompt(
        [
            StubField("severity", "Severity", "select", options=["sev1", "sev2"]),
            StubField("story_points", "Story Points", "number"),
        ]
    )
    # Frozen-grammar essentials survive in the prompt.
    for fragment in ("ORDER BY", "IS EMPTY", "assignee = me", "priority IN (high, blocker)"):
        assert fragment in prompt
    # Registry fields with their type/options.
    assert "severity" in prompt and "sev1, sev2" in prompt
    assert "story_points" in prompt and "number" in prompt
    # The output contract.
    assert '"slq"' in prompt and '"explanation"' in prompt


def test_nl_system_prompt_hides_ai_invisible_fields():
    prompt = prompts.nl_system_prompt(
        [StubField("salary_band", "Salary Band", "text", ai_visible=False)]
    )
    assert "salary_band" not in prompt
    assert "no custom fields" in prompt


def test_nl_system_prompt_enumerates_live_types_and_categories():
    prompt = prompts.nl_system_prompt(
        [], issue_types=["Bug", "Feature"], work_categories=[]
    )
    assert "Bug, Feature" in prompt
    assert "kind is ONLY the hierarchy level" in prompt
    worklog = prompts.nl_system_prompt(
        [], dialect="worklog", issue_types=["Bug"], work_categories=["Code Review", "Meeting"]
    )
    assert "issue.type" in worklog  # types render behind the delegation prefix
    assert "Code Review, Meeting" in worklog
    assert "NEVER a bare `state != Done`" in worklog or "issue.state" in worklog


def test_nl_system_prompt_enumerates_workflow_states_and_teaches_category_words():
    """RADD-1140: the model saw only `state != Done` and wrote `state = Fixed`
    on a workflow with no such state — a silent zero-row query. The live names
    ride in the prompt, and the finished/unfinished words map to `category`."""
    prompt = prompts.nl_system_prompt([], states=["Triage", "In Progress", "Done"])
    assert "Triage, In Progress, Done" in prompt
    assert "state ONLY for one of these names" in prompt
    assert "fixed" in prompt and "category = done" in prompt
    assert "open" in prompt and "category != done" in prompt
    worklog = prompts.nl_system_prompt([], dialect="worklog", states=["Done"])
    assert "issue.state ONLY" in worklog and "issue.category = done" in worklog
    assert "Workflow states" not in prompts.nl_system_prompt([])


def test_nl_retry_prompt_carries_query_and_error():
    prompt = prompts.nl_retry_prompt("open bugs", "priority = urgent", "unknown value 'urgent'")
    assert "open bugs" in prompt
    assert "priority = urgent" in prompt
    assert "unknown value 'urgent'" in prompt


def test_summarize_prompt_digest():
    prompt = prompts.summarize_user_prompt(
        key="TD-7",
        title="Render farm stalls",
        kind="issue",
        state="In Progress",
        priority="high",
        assignee="Hussein",
        labels=["urgent"],
        description="Farm nodes hang after 2h.",
        comments=[("Ana", "Reproduced on node 12.")],
        history=["2026-07-01 Hussein: state: Todo -> In Progress"],
        worklogs=["Total logged: 6h", "2026-07-02 Ana (Debugging) 4h: bisected the hang"],
    )
    for fragment in (
        "TD-7",
        "Render farm stalls",
        "In Progress",
        "urgent",
        "Farm nodes hang",
        "Ana: Reproduced on node 12.",
        "state: Todo -> In Progress",
        "Total logged: 6h",
        "bisected the hang",
    ):
        assert fragment in prompt


def test_summarize_prompt_omits_time_tracking_when_project_logs_none():
    prompt = prompts.summarize_user_prompt(
        key="TD-8",
        title="No timesheets here",
        kind="issue",
        state="Todo",
        priority="low",
        assignee=None,
        labels=[],
        description="",
        comments=[],
        history=[],
    )
    assert "Time tracking" not in prompt


def test_take_recent_keeps_newest_within_budget():
    entries = ["old", "middle-sized", "newest"]
    # Budget fits the last two only — the oldest is dropped, order kept.
    assert service.take_recent(entries, 18, len) == ["middle-sized", "newest"]
    # The newest entry survives even when it alone overflows the budget.
    assert service.take_recent(["a" * 50], 10, len) == ["a" * 50]
    assert service.take_recent([], 10, len) == []


def test_similar_prompt_lists_candidates():
    prompt = prompts.similar_user_prompt(
        key="TD-1",
        title="Login fails",
        description="500 on submit",
        candidates=[("TD-2", "Login broken", "users report 500"), ("TD-3", "Add SSO", "")],
    )
    assert "TD-1" in prompt and "TD-2" in prompt and "TD-3" in prompt
    assert "users report 500" in prompt


def test_history_line_formats():
    at = datetime(2026, 7, 1, 12, 0)
    actor = HistoryActor(id="00000000-0000-0000-0000-000000000001", name="Hussein")
    changed = HistoryEntry(
        id=1,
        at=at,
        actor=actor,
        type="item.updated",
        changes=[{"field": "state", "from": "Todo", "to": "Done"}, {"field": "description"}],
    )
    assert service.history_line(changed) == (
        "2026-07-01 Hussein: state: Todo -> Done; description changed"
    )
    related = HistoryEntry(id=2, at=at, actor=None, type="comment.created")
    assert service.history_line(related) == "2026-07-01 someone: comment.created"


# --- lenient JSON extraction ---


def test_extract_json_array_lenient():
    assert service.extract_json_array('[{"key": "TD-1", "score": 0.9}]') == [
        {"key": "TD-1", "score": 0.9}
    ]
    fenced = 'Sure! Here are the scores:\n```json\n[{"key": "TD-1", "score": 1}]\n```\nDone.'
    assert service.extract_json_array(fenced) == [{"key": "TD-1", "score": 1}]
    # A non-JSON '[' earlier in the reply is skipped, the first PARSEABLE array wins.
    assert service.extract_json_array("[see note] then [1, 2]") == [1, 2]
    assert service.extract_json_array("no arrays here") is None
    assert service.extract_json_array("[broken") is None


def test_extract_json_object_lenient():
    assert service.extract_json_object('{"slq": "state != Done", "explanation": "open"}') == {
        "slq": "state != Done",
        "explanation": "open",
    }
    fenced = 'Answer:\n```json\n{"slq": "assignee = me"}\n```'
    assert service.extract_json_object(fenced) == {"slq": "assignee = me"}
    assert service.extract_json_object("{oops") is None
    assert service.extract_json_object("nothing") is None


def test_parse_stream_objects_incremental():
    # An object split across chunks stays pending until its brace closes.
    found, offset = service.parse_stream_objects('[{"key": "TD-1", "sco', 0)
    assert found == []
    buffer = '[{"key": "TD-1", "score": 1}, {"key": "TD-2"'
    found, offset = service.parse_stream_objects(buffer, offset)
    assert found == [{"key": "TD-1", "score": 1}]
    buffer += ', "reason": "same {curly} trap"}]'
    found, offset = service.parse_stream_objects(buffer, offset)
    assert found == [{"key": "TD-2", "reason": "same {curly} trap"}]
    # Fully consumed: nothing new on a repeat call.
    assert service.parse_stream_objects(buffer, offset) == ([], len(buffer))


def test_clean_reason_entry_filters_and_clamps():
    seen: set[str] = set()
    allowed = {"TD-1", "TD-2"}
    assert service.clean_reason_entry(
        {"key": "TD-1", "score": 1.7, "reason": "dup"}, allowed, seen
    ) == {"key": "TD-1", "score": 1.0, "reason": "dup"}
    # Duplicate key, unknown key, boolean/absent score all drop.
    assert service.clean_reason_entry({"key": "TD-1", "score": 0.5}, allowed, seen) is None
    assert service.clean_reason_entry({"key": "XX-9", "score": 0.5}, allowed, seen) is None
    assert service.clean_reason_entry({"key": "TD-2", "score": True}, allowed, seen) is None
    # Empty reason -> None (the row keeps its base "semantic match" line).
    assert service.clean_reason_entry({"key": "TD-2", "score": 0.4, "reason": ""}, allowed, seen)[
        "reason"
    ] is None


# --- similar: normalization + rerank merge ---


def _hit(key: str, title: str = "t"):
    from radd.modules.search.service import SearchHit
    import uuid

    return SearchHit(
        item_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        key=key,
        title=title,
        snippet=None,
    )


def test_fts_candidates_normalizes_ranks():
    candidates = service.fts_candidates([(_hit("TD-1"), 0.8), (_hit("TD-2"), 0.4)])
    assert [c.score for c in candidates] == [1.0, 0.5]
    assert all(c.reason == "text match" for c in candidates)
    assert service.fts_candidates([(_hit("TD-1"), 0.0)])[0].score == 0.0
    assert service.fts_candidates([]) == []


async def test_similar_to_seed_is_semantic_first(monkeypatch):
    """When the vector pool answers, the OR-ed FTS pool must not
    even run — one shared common token was enough to surface an unrelated
    issue as a top 'text match'. FTS remains the fallback when semantic is
    off/empty.

    Patched on `similar` (RADD-902: `_semantic_pool`/`search_service`/
    `similar_to_seed` all live in `radd.modules.ai.similar` now — `service.py`
    only re-exports them, and a monkeypatch on the facade's re-exported
    attribute would not reach the call site running in `similar`'s own
    globals)."""
    semantic = [
        SimilarCandidate(item_key="TD-9", title="nine", score=0.8, reason="semantic match")
    ]

    async def pool(session, text, actor, *, item_id=None, exclude_item_id=None):
        return semantic

    def fts_must_not_run(*args, **kwargs):
        raise AssertionError("FTS must not run when the semantic pool answers")

    monkeypatch.setattr(similar, "_semantic_pool", pool)
    monkeypatch.setattr(similar.search_service, "similar_to_text", fts_must_not_run)
    result = await similar.similar_to_seed(None, "seed", None, exclude_item_id=None, limit=5)
    assert [c.item_key for c in result.candidates] == ["TD-9"]
    assert result.reranked is False

    async def empty_pool(session, text, actor, *, item_id=None, exclude_item_id=None):
        return []

    async def fts(session, text, *, user=None, exclude_item_id=None, limit=10):
        return [(_hit("TD-1"), 0.8)]

    monkeypatch.setattr(similar, "_semantic_pool", empty_pool)
    monkeypatch.setattr(similar.search_service, "similar_to_text", fts)
    result = await similar.similar_to_seed(None, "seed", None, exclude_item_id=None, limit=5)
    assert [c.item_key for c in result.candidates] == ["TD-1"]


def _candidate(key: str, score: float = 0.5) -> SimilarCandidate:
    return SimilarCandidate(item_key=key, title=f"title {key}", score=score, reason="text match")


def test_apply_rerank_merges_scores_and_filters():
    candidates = [_candidate("TD-1"), _candidate("TD-2"), _candidate("TD-3")]
    merged = service.apply_rerank(
        candidates,
        [
            {"key": "TD-2", "score": 0.9, "reason": "same stack trace"},
            {"key": "TD-1", "score": 0.3},
            {"key": "TD-99", "score": 1.0},  # unknown key -> ignored
            "garbage",  # malformed entry -> ignored
            {"key": "TD-3", "score": "high"},  # non-numeric score -> ignored
        ],
    )
    assert [c.item_key for c in merged] == ["TD-2", "TD-1"]  # score-descending, TD-3 filtered
    assert merged[0].score == 0.9 and merged[0].reason == "same stack trace"
    assert merged[1].reason == "text match"  # missing reason keeps the FTS one


def test_apply_rerank_clamps_and_rejects_unusable():
    clamped = service.apply_rerank([_candidate("TD-1")], [{"key": "TD-1", "score": 3.7}])
    assert clamped[0].score == 1.0
    # Nothing usable -> None, so the caller falls back to FTS order (reranked: false).
    assert service.apply_rerank([_candidate("TD-1")], [{"key": "TD-9", "score": 1}]) is None
    assert service.apply_rerank([_candidate("TD-1")], ["junk"]) is None


# --- request options (RADD-1273) ---


def _bare(**kw):
    return provider.openai_payload("SYS", "USER", model="m", max_tokens=8, **kw)


def test_reasoning_off_is_the_default_and_asks_the_template_not_to_think():
    payload = provider.finish_payload(
        _bare(), AiWireShape.OPENAI, reasoning=False, request_params={}, reasoning_budget_tokens=1024
    )
    assert payload[OPENAI_TEMPLATE_KWARGS_KEY] == {OPENAI_THINKING_FLAG: False}
    # ...and touches nothing else: the base payload is intact and unmutated.
    assert payload["messages"] == _bare()["messages"] and OPENAI_TEMPLATE_KWARGS_KEY not in _bare()


def test_reasoning_on_leaves_an_openai_model_to_its_default():
    payload = provider.finish_payload(
        _bare(), AiWireShape.OPENAI, reasoning=True, request_params={}, reasoning_budget_tokens=1024
    )
    assert payload == _bare()


def test_request_params_merge_last_and_win():
    params = {"temperature": 0.2, OPENAI_TEMPLATE_KWARGS_KEY: {OPENAI_THINKING_FLAG: True, "x": 1}}
    payload = provider.finish_payload(
        _bare(), AiWireShape.OPENAI, reasoning=False, request_params=params, reasoning_budget_tokens=1024
    )
    assert payload["temperature"] == 0.2
    # Nested objects merge key by key; the admin's value beats Radd's directive.
    assert payload[OPENAI_TEMPLATE_KWARGS_KEY] == {OPENAI_THINKING_FLAG: True, "x": 1}


def test_anthropic_reasoning_on_adds_thinking_inside_a_lifted_budget():
    base = provider.anthropic_payload("SYS", "USER", model="c", max_tokens=8)
    on = provider.finish_payload(
        base, AiWireShape.ANTHROPIC, reasoning=True, request_params={}, reasoning_budget_tokens=1024
    )
    assert on["thinking"] == {"type": "enabled", "budget_tokens": 1024}
    assert on["max_tokens"] == 8 + 1024
    off = provider.finish_payload(
        base, AiWireShape.ANTHROPIC, reasoning=False, request_params={}, reasoning_budget_tokens=1024
    )
    assert off == base  # the API's own default is no thinking
    # A forced tool call cannot be combined with thinking — structured stays silent.
    forced = provider.anthropic_payload("SYS", "USER", model="c", max_tokens=8, tool_schema={"type": "object"})
    assert provider.finish_payload(
        forced, AiWireShape.ANTHROPIC, reasoning=True, request_params={}, reasoning_budget_tokens=1024
    ) == forced


def test_request_params_cannot_replace_the_request_itself():
    from pydantic import ValidationError

    from radd.modules.ai.schemas import AiProviderCreate

    with pytest.raises(ValidationError):
        AiProviderCreate(name="x", wire_shape=AiWireShape.OPENAI, request_params={"messages": []})
    with pytest.raises(ValidationError):
        AiProviderCreate(name="x", wire_shape=AiWireShape.OPENAI, request_params=["not", "an", "object"])


# --- NL->SLQ retry decision ---


def test_nl_retry_decision():
    assert service.decide(0, None) is NlOutcome.ACCEPT
    assert service.decide(0, "unknown field 'foo'") is NlOutcome.RETRY
    assert service.decide(NL_MAX_ATTEMPTS - 1, None) is NlOutcome.ACCEPT
    assert service.decide(NL_MAX_ATTEMPTS - 1, "still bad") is NlOutcome.REJECT
