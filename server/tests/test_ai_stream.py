"""Provider-layer depth (spec 101): structured-output builders, SSE stream-line
parsers (the pure unit-test surface for streaming), and the wired client seam —
complete/complete_choice/embed/stream — over an httpx.MockTransport with a DB
role, no network.
"""

import json
import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.ai import client, provider, registry
from radd.modules.ai.schemas import AiProviderCreate, AiRoleAssign
from radd.modules.ai.types import AiRole, AiUpstreamError, AiWireShape

# --- pure: structured builders ------------------------------------------------


def test_openai_payload_structured_and_stream_flags():
    fmt = provider.json_schema_format({"type": "object"})
    payload = provider.openai_payload(
        "SYS", "USER", model="m", max_tokens=8, response_format=fmt, stream=True
    )
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["strict"] is True
    assert payload["stream"] is True
    # Defaults unchanged: no extra keys when not asked for.
    bare = provider.openai_payload("SYS", "USER", model="m", max_tokens=8)
    assert "response_format" not in bare and "stream" not in bare


def test_anthropic_payload_forces_the_answer_tool():
    schema = provider.choice_schema(["general", "content"])
    payload = provider.anthropic_payload(
        "SYS", "USER", model="m", max_tokens=8, tool_schema=schema
    )
    assert payload["tools"] == [
        {"name": provider.STRUCTURED_TOOL_NAME, "input_schema": schema}
    ]
    assert payload["tool_choice"] == {"type": "tool", "name": provider.STRUCTURED_TOOL_NAME}


def test_choice_schema_enumerates_answers():
    schema = provider.choice_schema(["a", "b"])
    assert schema["properties"]["choice"]["enum"] == ["a", "b"]
    assert schema["required"] == ["choice"]


def test_vision_content_parts_both_shapes():
    openai = provider.user_content(AiWireShape.OPENAI, "what is it", b"\x89PNG", "image/png")
    assert openai[0]["type"] == "image_url"
    assert openai[0]["image_url"]["url"].startswith("data:image/png;base64,")
    anthropic = provider.user_content(AiWireShape.ANTHROPIC, "what is it", b"\x89PNG", "image/png")
    assert anthropic[0]["type"] == "image"
    assert anthropic[0]["source"]["media_type"] == "image/png"
    # No image -> plain string content.
    assert provider.user_content(AiWireShape.OPENAI, "t", None, None) == "t"


def test_extract_structured_both_shapes():
    openai = {"choices": [{"message": {"content": '{"choice": "content"}'}}]}
    assert provider.extract_structured(AiWireShape.OPENAI, openai) == {"choice": "content"}
    anthropic = {
        "content": [
            {"type": "text", "text": "thinking..."},
            {"type": "tool_use", "name": "answer", "input": {"choice": "general"}},
        ]
    }
    assert provider.extract_structured(AiWireShape.ANTHROPIC, anthropic) == {"choice": "general"}
    with pytest.raises(AiUpstreamError):
        provider.extract_structured(AiWireShape.OPENAI, {"choices": [{"message": {"content": "no"}}]})
    with pytest.raises(AiUpstreamError):
        provider.extract_structured(AiWireShape.ANTHROPIC, {"content": [{"type": "text"}]})


def test_extract_embeddings_orders_by_index():
    data = {
        "data": [
            {"index": 1, "embedding": [0.3, 0.4]},
            {"index": 0, "embedding": [0.1, 0.2]},
        ]
    }
    assert provider.extract_embeddings(data) == [[0.1, 0.2], [0.3, 0.4]]
    with pytest.raises(AiUpstreamError):
        provider.extract_embeddings({"nope": []})


# --- pure: SSE stream-line parsers ---------------------------------------------


def test_openai_stream_delta_lines():
    line = 'data: {"choices": [{"delta": {"content": "Hel"}}]}'
    assert provider.openai_stream_delta(line) == "Hel"
    assert provider.openai_stream_delta("data: [DONE]") is None
    assert provider.openai_stream_delta("") is None
    assert provider.openai_stream_delta("event: ping") is None
    assert provider.openai_stream_delta('data: {"choices": [{"delta": {}}]}') is None
    assert provider.openai_stream_delta("data: not-json") is None


def test_anthropic_stream_delta_lines():
    line = 'data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "lo"}}'
    assert provider.anthropic_stream_delta(line) == "lo"
    started = 'data: {"type": "message_start", "message": {}}'
    assert provider.anthropic_stream_delta(started) is None
    other_delta = 'data: {"type": "content_block_delta", "delta": {"type": "input_json_delta"}}'
    assert provider.anthropic_stream_delta(other_delta) is None


# --- wired: the client seam over MockTransport ---------------------------------


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def chat_role(db):
    """A flushed (never committed) openai-shape provider holding chat+vision+embeddings."""
    row = await registry.create_provider(
        db,
        AiProviderCreate(
            name=f"mock-{uuid.uuid4().hex[:8]}",
            wire_shape=AiWireShape.OPENAI,
            base_url="http://mock.local/v1",
            api_key="k",
            default_model="test-model",
        ),
    )
    for role in (AiRole.CHAT, AiRole.VISION, AiRole.EMBEDDINGS):
        await registry.set_role(db, role, AiRoleAssign(provider_id=row.id))
    return row


@pytest.fixture
def mock_transport():
    """Install a MockTransport on the client seam; the test sets `handler`."""
    state: dict = {}

    def handle(request: httpx.Request) -> httpx.Response:
        state["request"] = request
        return state["response"]

    client.transport = httpx.MockTransport(handle)
    yield state
    client.transport = None


async def test_complete_round_trip(db, chat_role, mock_transport):
    mock_transport["response"] = httpx.Response(
        200, json={"choices": [{"message": {"content": "summary text"}}]}
    )
    reply = await client.complete(db, AiRole.CHAT, "SYS", "USER")
    assert reply == "summary text"
    sent = json.loads(mock_transport["request"].content)
    assert sent["model"] == "test-model"
    assert mock_transport["request"].url.path.endswith("/chat/completions")


async def test_complete_choice_structured_answer(db, chat_role, mock_transport):
    mock_transport["response"] = httpx.Response(
        200, json={"choices": [{"message": {"content": '{"choice": "content"}'}}]}
    )
    answer = await client.complete_choice(
        db,
        AiRole.VISION,
        prompt="humans or assets -> content",
        choices=["content", "general"],
        image_bytes=b"\x89PNG",
        image_media_type="image/png",
    )
    assert answer == "content"
    sent = json.loads(mock_transport["request"].content)
    assert sent["response_format"]["json_schema"]["schema"]["properties"]["choice"]["enum"] == [
        "content",
        "general",
    ]
    # The image rode as a data-URL content part.
    assert sent["messages"][1]["content"][0]["type"] == "image_url"


async def test_complete_choice_lenient_fallback_and_refusal(db, chat_role, mock_transport):
    # Not valid JSON, but the reply names a choice -> lenient match.
    mock_transport["response"] = httpx.Response(
        200, json={"choices": [{"message": {"content": "I'd say: GENERAL storage."}}]}
    )
    answer = await client.complete_choice(
        db, AiRole.VISION, prompt="p", choices=["content", "general"]
    )
    assert answer == "general"
    # Names nothing -> AiUpstreamError, the router treats it as fall-through.
    mock_transport["response"] = httpx.Response(
        200, json={"choices": [{"message": {"content": "cannot tell"}}]}
    )
    with pytest.raises(AiUpstreamError):
        await client.complete_choice(db, AiRole.VISION, prompt="p", choices=["content", "general"])


async def test_embed_round_trip(db, chat_role, mock_transport):
    mock_transport["response"] = httpx.Response(
        200,
        json={"data": [{"index": 0, "embedding": [0.1]}, {"index": 1, "embedding": [0.2]}]},
    )
    vectors = await client.embed(db, AiRole.EMBEDDINGS, ["a", "b"])
    assert vectors == [[0.1], [0.2]]
    assert mock_transport["request"].url.path.endswith("/embeddings")


async def test_stream_yields_deltas_across_frames(db, chat_role, mock_transport):
    frames = (
        'data: {"choices": [{"delta": {"role": "assistant"}}]}\n\n'
        'data: {"choices": [{"delta": {"content": "Hel"}}]}\n\n'
        'data: {"choices": [{"delta": {"content": "lo"}}]}\n\n'
        "data: [DONE]\n\n"
    )
    mock_transport["response"] = httpx.Response(
        200, content=frames.encode(), headers={"content-type": "text/event-stream"}
    )
    chunks = [chunk async for chunk in client.stream(db, AiRole.CHAT, "SYS", "USER")]
    assert chunks == ["Hel", "lo"]
    sent = json.loads(mock_transport["request"].content)
    assert sent["stream"] is True


async def test_stream_http_error_raises_upstream(db, chat_role, mock_transport):
    mock_transport["response"] = httpx.Response(502, text="bad gateway")
    with pytest.raises(AiUpstreamError):
        async for _ in client.stream(db, AiRole.CHAT, "SYS", "USER"):
            pass


# --- editor actions (spec 103) -------------------------------------------------


def test_editor_sse_frame_shapes():
    from radd.modules.ai import editor

    assert editor.sse_frame({"t": "hi\nthere"}) == 'data: {"t": "hi\\nthere"}\n\n'
    assert editor.sse_frame({}, event="done") == "event: done\ndata: {}\n\n"


def test_editor_user_prompt_marks_the_selection():
    from radd.modules.ai import editor

    prompt = editor.user_prompt("full doc", "the part", "make it better")
    assert "Instruction: make it better" in prompt
    assert "full doc" in prompt
    assert "replace ONLY this part" in prompt
    assert "Selection" not in editor.user_prompt("full doc", "", "x")


def test_editor_stream_request_requires_exactly_one_of_action_or_instruction():
    from radd.modules.ai.schemas import EditorStreamRequest

    with pytest.raises(ValueError):
        EditorStreamRequest(document="d")
    with pytest.raises(ValueError):
        EditorStreamRequest(document="d", action_id="refine", instruction="also this")
    assert EditorStreamRequest(document="d", action_id="refine").action_id == "refine"


async def test_editor_menu_lists_builtins_and_enabled_presets(db):
    from radd.modules.ai import editor
    from radd.modules.ai.schemas import AiPresetCreate

    preset = await registry.create_preset(
        db, AiPresetCreate(name="To bug template", prompt="Rewrite as a bug report")
    )
    await registry.create_preset(db, AiPresetCreate(name="Disabled one", prompt="x", enabled=False))
    actions = await editor.list_actions(db)
    ids = [a.id for a in actions]
    assert "refine" in ids and "format" in ids
    assert str(preset.id) in ids
    assert not any(a.label == "Disabled one" for a in actions)
    # Prompts never ship to the client.
    assert not any(hasattr(a, "prompt") for a in actions)


async def test_editor_resolve_instruction_builtin_preset_freeform(db):
    from radd.exceptions import NotFoundError
    from radd.modules.ai import editor
    from radd.modules.ai.schemas import AiPresetCreate, EditorStreamRequest

    builtin = await editor.resolve_instruction(
        db, EditorStreamRequest(document="d", action_id="fix_grammar")
    )
    assert "minimal" in builtin
    preset = await registry.create_preset(db, AiPresetCreate(name="P", prompt="Preset prompt"))
    resolved = await editor.resolve_instruction(
        db, EditorStreamRequest(document="d", action_id=str(preset.id))
    )
    assert resolved == "Preset prompt"
    freeform = await editor.resolve_instruction(
        db, EditorStreamRequest(document="d", instruction="  translate to French ")
    )
    assert freeform == "translate to French"
    with pytest.raises(NotFoundError):
        await editor.resolve_instruction(
            db, EditorStreamRequest(document="d", action_id="not-an-action")
        )


async def test_editor_stream_frames_end_with_done(db, chat_role, mock_transport):
    from radd.modules.ai import editor
    from radd.modules.ai.schemas import EditorStreamRequest

    frames_in = (
        'data: {"choices": [{"delta": {"content": "Better"}}]}\n\n'
        'data: {"choices": [{"delta": {"content": " text"}}]}\n\n'
        "data: [DONE]\n\n"
    )
    mock_transport["response"] = httpx.Response(
        200, content=frames_in.encode(), headers={"content-type": "text/event-stream"}
    )
    request = EditorStreamRequest(document="doc", selection="sel", action_id="refine")
    out = [f async for f in editor.stream_frames(db, request, "improve")]
    assert out[0] == 'data: {"t": "Better"}\n\n'
    assert out[-1] == "event: done\ndata: {}\n\n"


async def test_editor_stream_upstream_failure_is_an_in_band_error_frame(
    db, chat_role, mock_transport
):
    from radd.modules.ai import editor
    from radd.modules.ai.schemas import EditorStreamRequest

    mock_transport["response"] = httpx.Response(502, text="bad")
    request = EditorStreamRequest(document="doc", action_id="refine")
    out = [f async for f in editor.stream_frames(db, request, "improve")]
    assert len(out) == 1 and out[0].startswith("event: error\n")
    assert "502" in out[0]


async def test_commit_middleware_passes_event_streams_through():
    """The commit-before-send buffer must NOT hold back SSE — chunks flow the
    moment the response starts (spec 103; buffering would defeat streaming)."""
    from radd.middleware import CommitBeforeSendMiddleware

    sent: list[str] = []

    async def app(scope, receive, send):
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"text/event-stream")],
        })
        await send({"type": "http.response.body", "body": b"data: {}\n\n", "more_body": True})
        # If buffering were still on, nothing would have reached the wire yet.
        assert sent, "stream chunks were buffered until the app finished"
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def send(message):
        sent.append(message["type"])

    await CommitBeforeSendMiddleware(app)({"type": "http"}, None, send)
    assert sent == ["http.response.start", "http.response.body", "http.response.body"]


async def test_commit_middleware_still_buffers_ordinary_responses():
    from radd.middleware import CommitBeforeSendMiddleware

    sent: list[str] = []
    seen_inside: list[int] = []

    async def app(scope, receive, send):
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"application/json")],
        })
        await send({"type": "http.response.body", "body": b"{}"})
        seen_inside.append(len(sent))  # must still be 0 — the commit-race guard

    async def send(message):
        sent.append(message["type"])

    await CommitBeforeSendMiddleware(app)({"type": "http"}, None, send)
    assert seen_inside == [0]
    assert sent == ["http.response.start", "http.response.body"]
