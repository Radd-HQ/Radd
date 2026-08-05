# Radd backend bad-practices audit
`<repo>/server/src/radd` — read-only audit against the project's own non-negotiable rules (CLAUDE.md), 2026-08-05.

## Executive summary

| Category | Findings | Critical | Major | Minor |
|---|---|---|---|---|
| 1. Magic strings/numbers | 13 | 0 | 6 | 7 |
| 2. Exception hygiene | 6 flagged (of 96 `except Exception:`, 0 bare `except:`) | 0 | 1 | 5 |
| 3. Async/sync hazards | 4 | 1 | 1 | 2 |
| 4. N+1 query patterns | 6 | 1 | 0 | 5 |
| 5. SQLAlchemy hygiene | 3 | 0 | 0 | 3 |
| 6. Security smells | 4 | 0 | 0 | 4 |
| 7. Mutable defaults / module state / datetime | 3 | 0 | 0 | 3 |
| 8. Duplication (sampled) | 5 | 0 | 1 | 4 |
| 9. DI bypasses | 0 | — | — | — |
| 10. Dependencies | 2 | 0 | 0 | 2 |
| File size (~300-line rule) | 65 files >300, 20 >500 | — | — | — |

**Top 5 most important findings:**

1. **CRITICAL — `middleware.py:29-53`**: `CommitBeforeSendMiddleware` buffers the **entire response body in RAM** for every non-SSE response, including `FileResponse` — a backup-artifact download (`modules/backup/router.py:182`, unbounded size: DB dump + attachments) is held fully in memory before the first byte is sent.
2. **CRITICAL — `modules/items/service/queries.py:289-300`**: `_rebalance_ranks` issues **one UPDATE per work item across the entire table**, inside a user's drag-to-rank request. Against the documented 503k-item perf dataset that is 503k statements in one transaction.
3. **MAJOR — `modules/pluginmgr/boot.py:33`**: `except Exception: return {}` silently discards all plugin enable/disable state on **any** DB error at boot — the exact bug class (silently-failed plugin gating) this project already shipped once.
4. **MAJOR — `modules/ai/router.py:50-79` + `modules/ai/service.py:232-245`**: SSE endpoints hold the request-scoped DB session (and its open transaction/connection) across the entire upstream LLM stream (up to `ai_stream_timeout_seconds=120`), against a default pool of 5+10.
5. **MAJOR (class) — enums exist but are bypassed** in at least 6 places (`RuleType`, `ApproverKind`, `InstanceRole`, `ItemEvent.DELETED`, plus two comment-documented string vocabularies) — direct violations of non-negotiable rule 2, several within the same module that defines the enum.

---

## 1. Magic strings / numbers

**MAJOR — `modules/attachments/routing/engine.py:47,56,61`**
`if rule.rule_type == "user_choice":` … `if rule.rule_type == "cidr":` … `elif rule.rule_type == "llm":`
`RuleType` (StrEnum, same module: `modules/attachments/types.py:50-56`) defines exactly these values; the engine restates them as literals. A renamed enum member silently breaks routing. Fix: `RuleType.USER_CHOICE.value` etc. (the store already does this at `routing/store.py:44-48`).

**MAJOR — `modules/automations/engine.py:165`**
`kind: str  # "item_update" | "comment" | "create_item" | "http" | "notify" | "email" | "skip"` — a seven-value behavior vocabulary defined in a comment, compared as literals at lines 394-413, 510, 721. This is precisely what rule 2 exists to prevent (a typo in one branch is invisible). Fix: a `PlanKind(StrEnum)` in `automations/types.py`; `_apply_plan`'s if-chain then becomes exhaustive and checkable.

**MAJOR — `modules/workflow/guards.py:176`**
`if entry.get("kind") == "team":` — `ApproverKind(StrEnum)` with `TEAM = "team"` is defined **in the same module** (`workflow/types.py:86-91`). No dependency excuse. Fix: `ApproverKind(entry.get("kind")) is ApproverKind.TEAM`.

**MAJOR — `modules/auth/roles_router.py:351`**
`.where(UserModel.instance_role == "admin", ...)` — `InstanceRole.ADMIN` exists in the same package (`auth/types.py:10-12`) and every other call site uses it (`items/service/visibility.py:415`, `auth/preflight.py:79`, `workflow/router.py:94`). Fix: `InstanceRole.ADMIN.value`.

**MAJOR — `modules/ai/embeddings/embedder.py:48,67-75,149-160`**
`kind: str  # "item" | "doc"` plus `"drop_item"`/`"drop_doc"` literals built and compared in five places. Internal task vocabulary, no cross-module excuse. Fix: `EmbedTaskKind(StrEnum)`.

**MAJOR (class) — field-type wire literals restated three times in `workflow`**
- `modules/workflow/types.py:172-178` — `field_type in ("number", "duration")`, `== "date"`, `== "boolean"`
- `modules/workflow/guards.py:156-158` — `field_type in ("number", "duration")`, `== "date"`
- `modules/workflow/transitions.py:168-170` — `str(definition.type) == "date"`, `== "boolean"`

The docstring says "workflow stays ignorant of the fields module's enum" — but restating the wire vocabulary in three files is the drift the rule forbids. Even granting the no-dependency stance, workflow should define the vocabulary **once** (its own StrEnum mirroring the wire values, or import `fields.FieldType` — a `types.py` import is a public seam, and workflow already couples to the same strings).

**Minor — `modules/pluginmgr/service.py:96,99,142,171,323`**
`"bootstrap"` / `"installable"` returned and compared as bare strings (`kind == "bootstrap"`). Fix: `PluginOrigin(StrEnum)` next to `PluginState`.

**Minor — `modules/items/history.py:39-51,141`**
`RELATED_EVENT_TYPES = ("comment.created", …, "vcs.unlinked")` and `event.event_type.startswith("comment.")`. The comment says "Wire strings … Keep in sync with those modules' *Event enums" — a keep-in-sync comment is a standing drift risk. Same class: `modules/ai/embeddings/embedder.py:39-43` (`_ITEM_EVENTS = {"item.created", ...}`). Fix: importing another module's `types.py` enums is already accepted practice elsewhere (comments/attachments import `ItemEvent`-adjacent vocab); alternatively a kernel-level event-name registry (the kernel already registers events).

**Minor — `modules/comments/parents.py:129` and `modules/attachments/parents.py:112`**
`deleted_event="item.deleted"` — both modules already declare `depends_on` items; `ItemEvent.DELETED` exists (`items/enums.py:51`). Fix: use the enum.

**Minor — `backup/service.py:163`**
`if default.get("type") != "filesystem":` — `StorageHostType.FILESYSTEM` exists (`attachments/types.py:16-18`) and the function already imports `attachments.hosts`. Fix: use the enum.

**Minor — inline HTTP timeouts (tunables not in config.py)**
- `modules/sso/service.py:71,133` — `httpx.AsyncClient(timeout=10)`
- `modules/forgejo/admin_router.py:98` — `timeout=15`
- `modules/forgejo/backfill.py:62` — `timeout=30`

Every peer connector (`webhook_timeout`, `jira_timeout_seconds`, `ldap_timeout_seconds`, `ai_timeout_seconds`) has a Settings field; these three don't. Fix: `sso_http_timeout_seconds`, `forgejo_http_timeout_seconds` in `config.py`.

**Minor — `modules/timelogging/slq/suggest.py:146,155,163`**
`.limit(20)`, `.limit(50)`, `.limit(50)` inline. The items dialect froze this as `MAX_SUGGESTIONS = 20` (`items/slq/suggest_values.py:38`); the worklog dialect hardcodes three different numbers. Fix: reuse/mirror the named constant.

**Minor — named module-level tunables scattered outside config.py**
`events/cascade.py:49 BATCH_SIZE = 50`, `googlechat/types.py:14 BATCH_SIZE = 100`, `csat/types.py:22 BATCH = 200`, `ldap/groupsync.py:44 MAX_RECORDED_ERRORS = 20`. Named constants beat inline literals, but rule 2 says tunables live in `config.py` — every *other* consumer's batch size (`notify_batch`, `search_batch`, `automation_batch`) is a Settings field. Inconsistent; consolidate.

Legitimate non-findings noted: external wire vocabularies (`ai/provider.py` `"tool_use"`/`"content_block_delta"`, `gitlab/parsing.py` `"merged"`, `forgejo/router.py` `"published"`, `jiraimport/inference.py` Jira schema types) are foreign protocol constants, correctly not local enums — though hoisting them to named module constants would still help.

## 2. Exception hygiene

96 `except Exception:`/`except BaseException:` sites, **zero bare `except:`**. The overwhelming majority are the correct log-and-continue boundary shape (consumer loops, webhook receivers, per-item bulk operations, delivery fire-and-forget) with `logger.exception(...)` and often a rationale comment — the codebase has clearly internalized the RADD lesson. Both `except BaseException:` sites (`db.py:42`, `attachments/clients.py:91`) re-raise after cleanup: correct. Flagged:

**MAJOR (bug-hider) — `modules/pluginmgr/boot.py:26-34`**
```python
except Exception:
    return {}
```
No logging at all. The docstring justifies "table doesn't exist yet", but the catch swallows *every* failure — a transient DB outage at boot, a bad URL, a permissions error — and returns "no overrides". Consequence: a **disabled** optional plugin silently loads anyway, and an **enabled** installable plugin silently doesn't. This is the same failure class as the spec-104 `_IncludedRouter` bug the project documents ("the bare `except: pass` hid it, so disable changed nothing"). Fix: catch `ProgrammingError`/`OperationalError` for the missing-table case, `logger.exception` and (arguably) refuse to boot on anything else.

**Minor (bug-hider) — `modules/mcp/pages_bridge.py:36-40`**
`except Exception: continue` around `importlib.import_module` of pages submodules. The intent is "pages module absent → degrade", but the broad catch also hides a real `ImportError`-with-cause or syntax error inside `pages/service.py` — MCP page tools would silently vanish. Fix: catch `ImportError` only; log anything else.

**Minor — `kernel/capabilities.py:29-31`**
`except Exception: enabled = False; detail = {"error": "check failed"}` — the surface degrades correctly but the traceback is lost (no logger in the module). A permanently-broken check reads as "unconfigured" forever. Fix: add `logger.warning(..., exc_info=True)`.

**Minor — `backup/service.py:57`**
`except Exception:  # an empty database has no such table` — the comment names a specific condition; the catch accepts every condition (connection refused reads as "no version"). Fix: catch `ProgrammingError`.

**Minor — `modules/sso/service.py:404-407`**
`parse_flow_cookie` catches `Exception` for what is `ValueError`/`binascii.Error`/`json.JSONDecodeError`/`KeyError`. Behavior (None = refuse) is right; the net is wider than the fish. Narrow it.

**Minor — `modules/sso/router.py:102-104`**
The callback's final `except Exception` correctly logs and refuses, but it sits *after* a specific-refusal branch and will also convert programming errors into a user-facing "Sign-in failed" — acceptable for a leg that runs in an address bar, but worth an alerting hook since it can mask a broken provider config permanently.

## 3. Async/sync hazards

**CRITICAL — `middleware.py:29-53` — full-response RAM buffering**
```python
buffered.append(message)   # every http.response.body message, until the app returns
```
`CommitBeforeSendMiddleware` holds *all* response messages until the inner app (including session teardown) finishes, flushing early only for `text/event-stream`. Consequences:
- `GET /backups/{name}/download` (`modules/backup/router.py:182-187`, `FileResponse`) — the **entire artifact** (DB dump of a 503k-item instance + attachments, potentially GBs) accumulates in a Python list before the first byte leaves.
- Attachment proxy delivery (`modules/attachments/clients.py:110-118`) — bounded at 25 MB each, but N concurrent image loads each hold their full body.

The commit-race rationale doesn't apply to either: a file download commits nothing a follow-up request depends on. Fix: exempt responses by content-type/route the same way SSE is exempted (e.g. flush-through for `application/octet-stream`/`FileResponse` paths), or invert the design — commit explicitly before returning in the handful of write endpoints the Jira importer race actually involved.

**MAJOR — `modules/ai/router.py:50-62,65-79` + `modules/ai/service.py:232-245` — request session held across the LLM stream**
`StreamingResponse(service.summarize_stream_frames(session, ...))` — the generator calls `client.stream(session, ...)`, so the request-scoped session (with the open transaction from the prompt-building reads — commit happens in `get_session` teardown, after the stream ends) pins a pool connection for up to `ai_stream_timeout_seconds = 120`. `db.py:32` creates the engine with defaults (pool_size 5, max_overflow 10): ~15 concurrent AI streams exhaust the pool for the whole app. Fix: resolve the provider/model config *before* constructing the generator (it's the only thing `client.stream` needs the session for), close the transaction, and stream sessionless; or `await session.commit()` before returning the `StreamingResponse`.

**Minor — `modules/backup/router.py:224-232` — sync disk writes in an async endpoint**
`handle.write(chunk)` per 1 MiB chunk of an unbounded upload, plus `store.load(name)` (sync `stat`/header parse, `backup/store.py:102-112`) — all on the event loop. Local-disk writes are usually fast, but a slow volume (the backup dir is a mount by design) stalls every request. Fix: `asyncio.to_thread` the write loop (or write via `anyio.open_file`).

**Minor — `db.py:32` — engine defaults**
`create_async_engine(settings.database_url)` — no `pool_size`/`max_overflow`/`pool_pre_ping` tunables in Settings. Compounds the SSE finding; a dropped Postgres connection surfaces as a request error rather than a silent re-check. Fix: add `db_pool_size`/`db_max_overflow`/`db_pool_pre_ping` Settings fields.

Verified clean: all `smtplib`/`imaplib`/`ldap3`/PIL/minio/sync-httpx call sites are wrapped in `asyncio.to_thread` (`smtp.py` docstring contract is honored at all 5 call sites; `jiraimport` wire calls all go through `to_thread` in `snapshot/download.py:208-485`); `backup/postgres.py` uses `asyncio.create_subprocess_exec`.

## 4. N+1 query patterns

**CRITICAL — `modules/items/service/queries.py:289-300` — `_rebalance_ranks`**
```python
for index, item_id in enumerate(rows, start=1):
    await session.execute(update(WorkItem).where(WorkItem.id == item_id).values(rank=...))
```
Triggered from `set_rank` (`items/service/core.py:395`) inside a user request whenever a float midpoint collapses. It iterates **every item in the instance** (`select(WorkItem.id)` — not even scoped to the project) and issues one UPDATE each. On the documented 503k-item dataset: 503k round-trips in one interactive transaction, blocking the drag-and-drop that triggered it and lock-contending every concurrent item write. Fix: one statement —
`UPDATE work_items SET rank = ranked.rn * :step FROM (SELECT id, row_number() OVER (ORDER BY rank, created_at) rn FROM work_items) ranked WHERE work_items.id = ranked.id` — and scope it per project while at it.

**Minor — `modules/mcp/tools.py:73-77` and `modules/automations/engine.py:221-226` — project-by-key via full scan**
Both load `projects_service.list_projects(session)` (every project row) and scan in Python per lookup, per tool call / per rule action. `projects/service.py` already queries `Project.key == key` directly (line 22). Fix: one public `projects.service.get_by_key` used by both (also a duplication finding, §8).

**Minor — `modules/pages/backlinks.py:82-90`**
One query per `(space_slug, page_slug)` pair in a page body. Bounded by link count, but a link-heavy page pays per link. Fix: single query with `tuple_(PageSpace.slug, Page.slug).in_(...)`.

**Minor — `modules/items/bulk.py:115-141, 318-365`**
Per-item `session.get` + full `update_item` (each with its own permission/validation/event work) in the bulk loops. Semantically defensible (per-item skip reasons) and capped at `bulk_max_items = 500`, but 500 items × ~10 queries each is a slow request. Acceptable now; batch the shared reads (states, fields) if bulk grows.

**Minor — `modules/gitlab/router.py:83-99` / `modules/forgejo/router.py:181-207` — `_transition_merged`**
Per merged item: `get_project` + `list_states` (+ `pipeline.waiting_state_id`) then `update_item`. N is small (items referenced by one MR); fine, but the per-item `list_states` is cacheable per project within the loop.

**Minor — `modules/automations/engine.py:623-640` (scheduled rules)**
Per matched item `session.get(WorkItem, ...)` + full action run, capped at `automation_schedule_max_items = 200` with truncation logged — the cap makes it acceptable; a single `in_()` load would still halve the queries.

Verified clean: `items/hydration.py`, `views/service.py:_hydrate` (198-240), `dashboards`, `notify` recipients — all batch with id-maps and a per-request permissions cache; `groups/service.py` BFS batches per depth level.

## 5. SQLAlchemy hygiene

**Minor — `modules/auth/service.py:614-615, 702-717, 1023-1066` — f-string SQL identifiers**
`sql(f"UPDATE {table} SET {user_col} = :dst WHERE {user_col} = :src")` etc. Identifiers come from the code-owned `_MERGE_REPOINT` registry, values are bound — no injection today, but nothing *enforces* that a future registry entry is a valid identifier. Fix: assert identifiers against `Base.metadata.tables` (or `re.fullmatch(r"[a-z_]+")`) at registry definition; one guard covers all ten sites.

**Minor — `modules/jiraimport/rollback.py:223-236` — SQL identifiers from DB-stored JSON**
`assignments = ", ".join(f"{column} = ..." for column, value in before.items())` — column names are read out of `jira_import_records.before` (JSONB) and interpolated raw into `text()`. The write path is the importer itself (admin-gated), so exploitation requires DB write access, but this is the one place in the codebase where *stored data* becomes SQL syntax. Fix: validate `before` keys against the target table's real column set before interpolating.

**Minor — index/session hygiene otherwise good** (positive finding)
Spot-checked hot models: `work_items` (project_id+rank composite, all FKs indexed), `worklogs` (item/project/author/category/worked_on), `notifications` (user_id+read_at composite), `events` (entity composite + event_type). `TimestampMixin` sets `eager_defaults` with the async rationale documented. Commit-in-loop occurrences (consumers, jiraimport stages) are deliberate checkpointing, not accidents. No `expire_on_commit` foot-guns (`False` set once in `db.py:33`).

## 6. Security smells

**Minor — automation `http` action + webhooks are SSRF-by-configuration**
`modules/automations/engine.py:401-408` POSTs to any stored URL from inside the cluster (signed, but unrestricted destination); webhook dispatcher likewise. Rule-writing is admin-gated, so this is accepted-risk, but in-cluster it can reach Garage admin ports, the metadata service, etc. Fix (cheap): an optional egress-denylist Setting (private CIDRs off by default for cloud deploys), documented in `docs/deploy.md`.

**Minor — `config.py:15` — `session_cookie_secure: bool = False`**
Documented ("enable behind HTTPS"), but a deploy that forgets ships session cookies over HTTP. Fix: the deploy chart should set it; better, default `True` and make dev opt out (dev is the minority environment that can't do HTTPS).

**Minor — SSO metadata/JWKS caches never expire** (`modules/sso/service.py:47-48`)
`_metadata_cache`/`_jwks_clients` keyed by provider id, refreshed only on restart. A provider that rotates its JWKS URI or endpoints keeps failing until restart (PyJWKClient itself refreshes keys, so key *rotation* is fine — endpoint changes are not). Fix: TTL the metadata cache.

**Minor — defense-in-depth on the two f-string-SQL items above** (§5) — listed here for cross-reference.

Verified clean (worth recording): raw tokens never stored (sha256, `auth/security.py:1`), constant-work password verify with dummy hash, `hmac.compare_digest` on all three webhook secrets (gitlab/forgejo/alertmanager), OIDC has PKCE + state + nonce + pinned Google issuer, no open redirects (all `RedirectResponse` targets are fixed paths or server-minted presigned URLs), no `eval`/`exec`/`pickle`/`yaml.load`/`md5`/`verify=False`, no CORS middleware (same-origin SPA — correct), attachment filenames quote-stripped in Content-Disposition, backup upload writes under a server-generated name and validates before accepting, tar extraction uses `filter="data"`. The router sweep found no endpoint missing an authz dependency: every apparently-open route is deliberately public (webhooks verify secrets, public KB/CSAT/forms are token- or flag-gated, the websocket authenticates the session cookie in-handler at `realtime/router.py:18-30`).

## 7. Mutable defaults, module state, datetime

**No mutable default arguments found** (checked `=[]`, `={}`, `=set()` in signatures — zero hits).

**Minor — write-through module-level snapshots go stale under >1 web process**
- `modules/sso/registry.py:32` `_snapshot` — login-page provider buttons, "refreshed on write + at startup". An admin edit in worker A leaves worker B serving the old button list until restart.
- `modules/ai/registry.py:298` `_role_snapshot` — same pattern; its comment argues the *worker split* case but not the multi-web-replica case.
- `modules/attachments/hosts.py:245` `_default_snapshot`, `modules/attachments/clients.py:240` `_cache` — same family (the client cache keys on host row state, so it self-heals; the default snapshot doesn't).

Today the deployment runs one web replica, so this is latent — but it's the kind of latent that surfaces as "the button appeared for some users". Fix: TTL these snapshots (they exist to avoid a per-request query; a 30 s TTL keeps that win) or listen on the realtime event stream the app already has.

**Minor — the naive-UTC idiom is consistent but hand-copied 15×** — see §8. One inconsistency: `modules/attachments/movejob.py:100,110,165` uses `timezone.utc` where everywhere else uses `UTC`. No deprecated `datetime.utcnow()` anywhere (good); no naive `datetime.now()` anywhere (good).

## 8. Copy-paste duplication (sampled)

**MAJOR — 15 private copies of the naive-UTC clock**
`def _utcnow()/_now(): return datetime.now(UTC).replace(tzinfo=None)` exists in `webhooks/service.py:31`, `auth/security.py:38`, `releases/service.py:17`, `cycles/history.py:19`, `notify/emailer.py:25`, `notify/service.py:15`, `automations/service.py:53`, `automations/scheduler.py:25`, `slas/evaluation.py:42`, `csat/service.py:25`, `backup/service.py:37`, `backup/scheduler.py:28`, `pages/service.py:45`, `jiraimport/runs.py:60`, `jiraimport/snapshot/download.py:76` — plus ~15 inline copies of the expression. This is the timestamp convention of the entire schema, defined 30 times. For a codebase that ran a dedicated duplication sweep, this is the biggest survivor. Fix: one `radd.clock.utcnow()` (kernel-adjacent, like `QueryError`); mechanical replace.

**Minor — `_project_by_key` twice, both wrong the same way** — `modules/mcp/tools.py:73` and `modules/automations/engine.py:221` (§4). Slightly different semantics (`.upper()` vs `.strip().casefold()`), so they'd also answer differently on odd input. Fix: one `projects.service.get_by_key`.

**Minor — `MAX_QUERY_CHARS = 200` twice** — `modules/search/types.py:22` and `modules/pages/types.py:14`. Same concept, will drift. One home (search is the owner; pages already delegates search plumbing).

**Minor — gitlab/forgejo connector parallels** — `_transition_merged` (`gitlab/router.py:83-99` vs `forgejo/router.py:181-207`) and the webhook verify/parse/link skeletons. Forgejo's has real spec-112 differences, so full extraction is premature, but the shared inner loop (resolve state → skip-if-there → `update_item` → log-and-continue) is one helper in `vcs` waiting to exist; the next connector will copy it a third time.

**Acknowledged, not findings**: `notify/consumer.py` and `search/indexer.py` hand-roll consume loops that resemble `events/runner.py` — the runner's docstring explicitly names them and why they stay separate (bootstrap-over-backlog, savepoint-per-event). That is documented divergence, not drift. `jiraimport` `MAX_RECORDED_PROBLEMS` 500 vs 1000 (`snapshot/download.py:62`, `runs.py:56`) are different surfaces with different comments — defensible, but a shared constant with two multipliers would be tighter.

## 9. Dependency-injection bypasses

**None found.** Both engines outside `db.py` are justified: `modules/pluginmgr/boot.py:26` (sync, pre-app, disposed — though see its exception finding) and none other. All 36 `SessionLocal` importers are background loops, consumers, startup seeds, or the websocket handler (which cannot use the request-scoped dependency's lifecycle for a long-lived socket) — no request handler constructs its own session.

## 10. Dependencies (pyproject)

**Minor — floor pins only, but `uv.lock` is present and authoritative** — `fastapi>=0.115` etc. with a committed lockfile is the correct uv shape; no action. All declared deps verified imported (minio and PIL lazily, matching their per-plugin-dependency declarations; `python-multipart` is FastAPI's form-parsing requirement; `alembic` runs from `server/migrations`).

**Minor — `modules/ldap/__init__.py:20-21` claims an extra that doesn't exist**
`# Maps to the 'radd[ldap]' extra` / `python_deps=("ldap3",)` — but `pyproject.toml` has no `[project.optional-dependencies] ldap`; `ldap3` is a core dependency. Either the comment lies or the intent (LDAP as an optional extra, like `localembed`) was never landed. Fix: add the extra and move `ldap3` into it (matching the plugin-platform §14 design the comment cites), or fix the comment.

## File size (~300-line rule)

65 files exceed 300 lines; 20 exceed 500. The worst, with seam assessment:

| File | Lines | Natural seams |
|---|---|---|
| `modules/auth/authz.py` | 1099 | Yes — its own markers: pure decision core (86-273) / the seam (275-384) / batched+downstream seams (385+) / `PermissionSource` explain machinery (633+). Three files. |
| `modules/auth/service.py` | 1087 | Yes — users / sessions+view-as / API tokens / merge+delete (the raw-SQL repoint block at 600-1070 is a self-contained `lifecycle.py`). |
| `modules/views/service.py` | 969 | Yes — sharing resolution / SLQ+axis validation (311-487) / scope+access / CRUD. The validation block alone is ~180 lines. |
| `modules/auth/types.py` | 818 | Yes — enums / ResourceSpec+CRUD registry (296-476) / relations (477-554) / plugin-contributable RBAC (555+). |
| `modules/automations/engine.py` | 736 | Yes — trigger classification / condition matching / planning (160-425) / application / scheduled runs (529+). Planning vs applying is the clean cut. |
| `modules/ai/service.py` | 728 | Yes — summarize / similar / NL→SLQ are three marker-separated features sharing almost nothing. |
| `modules/mcp/tools.py` | 693 | Yes — resolvers vs per-domain handler groups; spec-114's own `McpToolSpec` registry is the mechanism to split along. |
| `modules/jiraimport/runs.py` | 672 | Partial — staged pipeline; stages are functions but intertwined via run bookkeeping. |

Not urgent individually, but the two auth files are also the two most security-critical files in the repo — splitting them is a review-ability win, not cosmetics.

---

## Systemic fixes

1. **Make the enum the only way to say it.** The codebase *has* the enums; the violations are all bypasses. Add a ruff-enforceable guard: a small AST/grep check in CI (like `test_route_shadowing.py`) that flags `== "<member>"` where the literal equals a member value of any StrEnum defined in the same module — that alone catches `RuleType`, `ApproverKind`, `InstanceRole`, `PluginState`-adjacent literals mechanically. For cross-module event names, decide once: either module `types.py` imports are a blessed seam (they already are in practice — comments/attachments import items vocab) and the "keep in sync" comments get replaced with imports, or the kernel's event registry grows a lookup and both `items/history.py` and the embedder read it.

2. **One clock.** `radd.clock.utcnow()` (naive-UTC, documented as the schema convention) replaces 15 private helpers and ~15 inline copies in one mechanical sweep. Same sweep normalizes `timezone.utc` → `UTC`.

3. **Exceptions: "no catch without a logger" as a lint.** The codebase is 90% there; the failures (`pluginmgr/boot.py`, `pages_bridge.py`, `kernel/capabilities.py`) are exactly the unlogged ones. `ruff` rules `BLE001` + `S110`/`S112` (`try-except-pass`/`continue`) are already half-adopted via `noqa` annotations — turn them on repo-wide so every broad catch needs either a logger call or an explicit `noqa` with rationale, which is the house style anyway. Separately: any `except Exception` whose comment names a *specific* expected error (missing table, bad cookie) should catch that error.

4. **Streams and files bypass the buffer.** Rework `CommitBeforeSendMiddleware` from "buffer everything except SSE" to "buffer only what needs it": flush-through on `content-length` above a threshold or on octet-stream/file content-types, mirroring the existing SSE carve-out. This fixes backup downloads and attachment proxying in one place. Then audit the two long-lived-session patterns (`ai` SSE, any future stream) with one rule: **a response generator never captures the request session** — resolve what you need, commit, then stream.

5. **Set-based writes for set-sized data.** `_rebalance_ranks` is the acute case, but adopt the principle: any loop whose body is a single UPDATE/DELETE derived from the loop variable becomes one statement (window functions for rank respacing, `IN` lists elsewhere). The perf-seed dataset (503k items) is the test bed the project already maintains — run drag-to-rank against it once and the finding demonstrates itself.

6. **Tunables sweep into Settings.** One pass moving the inline httpx timeouts and the stray `BATCH`/`MAX_*` module constants into `config.py` sections beside their siblings, plus new `db_pool_*` fields. Mechanical, low-risk, and it restores the "config.py is the complete tunables inventory" property the file's excellent comments assume.

7. **Snapshot caches get TTLs.** One tiny `Snapshot[T]` helper (value + loaded-at + ttl + async refresh) replaces the four hand-rolled module-level caches (`sso`, `ai` roles, attachment hosts, SSO metadata) and removes the multi-replica staleness class before the deployment ever scales past one web pod.
