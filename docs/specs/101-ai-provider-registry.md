# Spec 101 — the AI provider registry: models as rows, roles as contracts

**.** The env-only single provider of spec 46 becomes a DB registry
with model ROLES, structured output, embeddings, and streaming — the shared
foundation specs 102 (storage LLM routing) and 103 (editor AI + semantic
search) stand on.

## Why

Spec 46 could name exactly one endpoint (`RADD_AI_PROVIDER` + three siblings)
and needed a redeploy to change. The new features need SEVERAL models at once —
a chat model for editor actions, an embedding model for semantic search, a
vision model for storage routing — often on different endpoints (a cloud model
for prose, a local vLLM for images that must not leave the network).

## What

- **`ai_providers`** rows: name, wire shape (`openai` = any OpenAI-compatible
  /chat/completions — vLLM/Ollama/LiteLLM/OpenAI — `anthropic`, or `local`),
  base_url, api_key (redacted reads, empty-on-update keeps), default model.
  Env config seeds ONE row + the chat role once, the jiraimport-connections
  pattern; the `ai_*` env keys are seed-only afterwards.
- **The `local` wire shape** (addendum): the plugin SHIPS a CPU
  embedding backend (`localembed.py`, fastembed/ONNX behind the optional
  `radd[localembed]` extra — in the container image by default), so semantic
  search needs no external model server at all. A LOCAL provider carries only
  a model name (default `BAAI/bge-small-en-v1.5`, 384d; catalog via
  `GET /ai/local-embed`), can hold ONLY the embeddings role (chat/vision
  assignments 422 both directions), refuses base_url/api_key, and Test runs
  one embedding (first run includes the weight download into
  `RADD_LOCAL_EMBED_CACHE` — pre-seed it on air-gapped deploys).
- **`ai_model_roles`**: `chat | embeddings | vision` → provider + model (row
  model falls back to the provider default). Rows, not JSONB: deleting a
  provider cascades its assignments. Assigning embeddings to an Anthropic
  provider is a 422 — that API has no embeddings endpoint.
- **`ai_preset_prompts`**: the admin prompt library spec 103's editor menu
  serves. Prompt text never ships to a client.
- **The client seam** (`ai/client.py`) — five role-addressed calls every module
  uses: `complete`, `complete_structured` (json_schema on the OpenAI shape, a
  forced tool call on Anthropic), `complete_choice` (enum-constrained, optional
  image — the spec-102 routing contract: the model cannot invent an unmapped
  answer), `embed`, and `stream` (SSE deltas; the codebase's first streaming
  primitive). Pure payload builders + SSE line parsers live in `provider.py`
  and are the unit-test surface.
- **Feature toggles**: six instance scoped-settings keys (editor_actions,
  semantic_search, storage_routing, summarize, nl_slq, similar_rerank);
  `features.feature_enabled` = toggle AND role resolvable; dormant features
  keep the spec-46 404 convention. Editor actions additionally honor a
  per-user `preferences["ai.editor_actions"]` opt-out (spec-94 idiom) — a
  preference, not security.
- **Settings → AI**: provider CRUD + a Test button (max_tokens=1 probe,
  failures as data), the three role rows (anthropic disabled in the embeddings
  row with the reason on hover), the toggles, the preset library. The instance
  Server pill links here.
- The sync `CapabilitySpec` check reads a process-local role snapshot refreshed
  at startup and on admin writes (a worker process's snapshot staleness is
  harmless — it never serves /capabilities).

## Invariants tested

Seed-once; role resolution (role model > provider default; nameless = not
callable); the embeddings/anthropic guard both directions (assignment AND
flipping a provider's shape while holding the role); credential round-trip;
stream parsers and the wired seam over `httpx.MockTransport`.

## Known simplifications

No per-request rate limiting (nothing in the codebase has it yet). Structured
calls are non-streaming by construction. `Socket.AI_PROVIDER` remains a dormant
seam — the DB registry supersedes it for now.
