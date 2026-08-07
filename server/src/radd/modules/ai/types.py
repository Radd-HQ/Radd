"""Enums, schemas, errors, and tunable constants for the AI layer (spec 46)."""

import uuid
from enum import StrEnum

from pydantic import BaseModel, Field

from radd.exceptions import RaddError


class AiWireShape(StrEnum):
    """Wire protocol a provider speaks (spec 101; formerly `AiProvider`)."""

    OPENAI = "openai"  # any OpenAI-compatible /chat/completions (LiteLLM/Ollama/vLLM/OpenAI)
    ANTHROPIC = "anthropic"  # native Anthropic /v1/messages
    LOCAL = "local"  # the plugin's built-in CPU embedding backend (embeddings role ONLY)


class AiRole(StrEnum):
    """What a configured model is FOR. Features resolve a role, never a provider."""

    CHAT = "chat"  # editor actions, summarize, NL->SLQ, similar rerank
    EMBEDDINGS = "embeddings"  # semantic search vectors (OpenAI-shape only)
    VISION = "vision"  # storage routing image classification (spec 102)


class AiProviderSource(StrEnum):
    """Where a provider row came from — env-seeded rows are ordinary editable rows."""

    ENV = "env"
    USER = "user"


class AiFeature(StrEnum):
    """Per-feature instance toggles (spec 101, Settings → AI). A feature is live
    when its toggle is on AND its role resolves to a provider."""

    EDITOR_ACTIONS = "editor_actions"  # spec 103: /refine, /format, presets, freeform
    SEMANTIC_SEARCH = "semantic_search"  # spec 103: pgvector hybrid search
    STORAGE_ROUTING = "storage_routing"  # spec 102: LLM routing rules
    MAIL_ROUTING = "mail_routing"  # RADD-961: pick a project from the email's content
    SUMMARIZE = "summarize"  # spec 46
    NL_SLQ = "nl_slq"  # spec 46
    SIMILAR_RERANK = "similar_rerank"  # spec 46


# Wire-shape default endpoints, used when a provider's base_url is empty.
DEFAULT_BASE_URLS: dict[AiWireShape, str] = {
    AiWireShape.OPENAI: "https://api.openai.com/v1",
    AiWireShape.ANTHROPIC: "https://api.anthropic.com",
}

# Required header value on every Anthropic request.
ANTHROPIC_VERSION = "2023-06-01"

# Digest caps for the summarize prompt — keep the context small and predictable.
# Summarize digest budgets: each section keeps its NEWEST entries whole until
# the section's char budget runs out (`take_recent`), so long dogfood threads
# contribute their recent hundred comments, not their last twelve. Still far
# under any chat model's context window.
SUMMARY_MAX_DESCRIPTION_CHARS = 4000
SUMMARY_MAX_COMMENT_CHARS = 2000
SUMMARY_COMMENTS_BUDGET_CHARS = 32_000
SUMMARY_HISTORY_BUDGET_CHARS = 4_000
SUMMARY_WORKLOG_BUDGET_CHARS = 3_000
SUMMARY_MAX_WORKLOG_NOTE_CHARS = 200

# /items/{id}/similar: response size bounds + the FTS candidate pool handed to
# the (optional) LLM rerank — wider than the response so the model can filter.
SIMILAR_DEFAULT_LIMIT = 5
SIMILAR_MAX_LIMIT = 20
SIMILAR_CANDIDATE_POOL = 15

# Reason attached to pure-FTS candidates (AI disabled, or the rerank fell back).
FTS_MATCH_REASON = "text match"

# NL->SLQ: one retry with the compile error in-prompt, then 422.
NL_MAX_ATTEMPTS = 2

# Editor AI actions (spec 103): request size caps + a roomier completion budget
# than ai_max_tokens (a /format of a long description needs the whole text back).
EDITOR_DOCUMENT_MAX_CHARS = 100_000
EDITOR_SELECTION_MAX_CHARS = 30_000
EDITOR_INSTRUCTION_MAX_CHARS = 2_000
EDITOR_MAX_TOKENS = 4096


class EditorAction(StrEnum):
    """Builtin editor AI actions; admin preset prompts extend the menu at runtime."""

    REFINE = "refine"
    FORMAT = "format"
    SUMMARIZE_SELECTION = "summarize_selection"
    FIX_GRAMMAR = "fix_grammar"


class EditorActionKind(StrEnum):
    BUILTIN = "builtin"
    PRESET = "preset"


class NlOutcome(StrEnum):
    """What to do after one NL->SLQ generation attempt (pure decision, tested)."""

    ACCEPT = "accept"
    RETRY = "retry"
    REJECT = "reject"


class AiEntity(StrEnum):
    AI = "ai"
    PROVIDER = "ai_provider"
    ROLE = "ai_role"
    PRESET = "ai_preset"


# --- errors (module exception handlers map these to clean JSON responses) ---


class AiDisabledError(RaddError):
    """An AI endpoint was hit while its role has no configured provider -> clean 404."""

    def __init__(self) -> None:
        super().__init__("AI is not configured")


class AiConfigError(RaddError):
    """An invalid registry configuration was attempted -> clean 422 (spec 101)."""


class AiUpstreamError(RaddError):
    """The provider call failed (network/HTTP/shape) -> clean 502, never a stack trace."""


class AiInvalidQueryError(RaddError):
    """NL->SLQ still failed after the retry -> 422 carrying the bad query + error."""

    def __init__(self, slq: str, error: str):
        self.slq = slq
        self.error = error
        super().__init__("generated SLQ failed to compile")


# --- schemas ---


class AiStatus(BaseModel):
    """GET /ai/status — the frontend gates its AI affordances on `enabled` (the
    chat role resolves at all) and, since spec 101, per-feature on `features`
    (toggle AND role resolvable). Both are current API; provider/model details
    live on /ai/providers and /ai/roles."""

    enabled: bool
    features: dict[str, bool] = {}
    # Instance delivery preference (not a feature — needs no role): stream
    # summaries/reasons progressively vs complete-then-show.
    stream_responses: bool = False


class SummarizeResponse(BaseModel):
    summary: str  # markdown; not stored anywhere


class SimilarCandidate(BaseModel):
    """One candidate duplicate: FTS-scored, or LLM-scored when AI is enabled."""

    item_key: str
    title: str
    score: float  # 0..1 — normalized FTS rank, or the LLM's same-issue score
    reason: str


class SimilarResponse(BaseModel):
    candidates: list[SimilarCandidate]
    # False = raw FTS order (AI disabled, or the rerank reply didn't parse).
    reranked: bool


# POST /ai/similar seeds from caller-supplied text (a comment, a draft) — cap it
# the way the editor endpoints cap their documents.
SIMILAR_TEXT_MAX_CHARS = 20_000


class SimilarReasonsRequest(BaseModel):
    """POST /items/{id}/ai/similar/reasons — the candidate keys the client is
    DISPLAYING, so the streamed reasons match the visible rows exactly (the
    pools are not perfectly deterministic between two calls). The server
    re-resolves titles under the caller's RBAC; unknown/unreadable keys are
    silently absent from the stream."""

    keys: list[str] = Field(min_length=1, max_length=SIMILAR_MAX_LIMIT)


# SSE responses (editor stream, summarize stream, similar reasons) share these.
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    # Tells nginx-style proxies not to buffer the stream.
    "X-Accel-Buffering": "no",
}


class SimilarTextRequest(BaseModel):
    """Find issues similar to a piece of TEXT (read-mode AI menu on comments):
    same fused pools as /items/{id}/similar, minus the LLM rerank — a rerank
    needs a source issue to compare against, and a text seed has none."""

    text: str = Field(min_length=1, max_length=SIMILAR_TEXT_MAX_CHARS)
    # The item the text belongs to (a comment's issue) — excluded from results.
    exclude_item_id: uuid.UUID | None = None


class SlqDialect(StrEnum):
    """Which SLQ surface the NL ask targets (spec 98: dialects are rooted at
    the entity they RETURN — the timesheet's rows are worklogs, so item fields
    ride the `issue.` prefix there)."""

    ITEMS = "items"
    WORKLOG = "worklog"


class NlQueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    dialect: SlqDialect = SlqDialect.ITEMS


class NlQueryResponse(BaseModel):
    slq: str  # compiles against the field registry (validated server-side)
    explanation: str
