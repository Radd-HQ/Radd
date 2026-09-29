# Radd — working agreements

Self-hosted, AI-native issue tracker + wiki, LIVE on project.radd-hq.com. **The current release is
whatever the newest git tag says.** What each wave built, and why, is `BUILD-LOG.md` (one entry per wave,
newest first); the module map is `docs/modules.md`; the build specs are `docs/specs/`; the RADD project on
the live instance is the record of every issue. Running it: `docs/deploy.md`. Research: `research/`.

## Development rules (non-negotiable)

1. **Everything is a module/plugin.** Features live in `server/src/radd/modules/<name>/`, expose a `plugin: RaddPlugin`, and are assembled from config (`RADD_MODULES`). Pieces must be interchangeable: modules talk to each other only through public `service.py` functions, emitted events, and declared extension points — never by reaching into another module's tables or internals. **Spine-table exception (RADD-885, enforced by `tests/test_module_contracts.py`):** the models of `auth` (User), `projects`, `items` (WorkItem), `workflow` (State), `teams`, and `fields` (FieldDefinition) are the measured de-facto spine and may be imported directly for READS (FKs, joins) — writes still go through the owner's service; every other module's `models.py` is off-limits, with the audit's residue frozen in the test's burn-down allowlist. Every cross-module import must be DECLARED: `depends_on` when the target loads first, `weak_depends` for deferred reverse reaches — the same test refuses undeclared edges. **A core module never reaches an OPTIONAL plugin** (RADD-1349; `test_core_modules_never_reach_optional_plugins`): it dispatches a hook or reads a kernel socket (`kernel/sockets.py`) the plugin provides, so disabling the plugin withdraws it. `except ImportError` and `settings.modules` cannot see a runtime disable and are never a guard.
2. **No hardcoded magic values.** Anything that names a behavior, state, or type is a `StrEnum` or a dataclass/Settings field. String literals appearing in data (event types, field types, entity types) are enum members. Tunables live in `config.py`.
3. **Document the connections.** `docs/modules.md` is the map: every new module, event type, or cross-module dependency gets a row/line there in the same change. A new contributor (or future session) must be able to navigate from that file alone.
4. **Tests only where they earn their keep.** No per-endpoint unit tests. Test core invariants that many modules depend on (custom-field validation, event emission, permission checks when they land). Everything else is verified by exercising the running app (UI, API docs, sample-data import).
5. **Ship small, viewable slices.** Every work session should end with something you can run and see (the UI, the API docs, a proof script). Prefer many small files/modules over big ones; if a file pushes past ~300 lines, split it. No speculative frameworks.
6. **The work is tracked in Radd itself.** Every bugfix, feature and plan exists as an item in the **RADD** project on <https://project.radd-hq.com> before it is built — see the section below. Radd is the tracker; a change that only exists in a commit message is untracked work.

## Tracking work on the live instance

`project.radd-hq.com` runs this project, and its **RADD** project is the record: the
first five months are backfilled from the git history and `docs/specs/`, everything
since is filed as it happens.

**This project is also the product's demonstration.** People land on it to decide
whether Radd is worth using, and what they see is whichever features this project
actually exercises. A tracker whose own project ignores half the tracker is not a
convincing argument. So: use the feature that fits the work — cycles for cadence,
releases for what shipped, subtask checklists for steps, dashboards for reporting —
rather than reducing everything to a flat list of tickets. Never with invented data:
a fabricated worklog makes the timesheet a lie in order to make a screenshot prettier.

### The shape of work

| Level | Is | Rule |
|---|---|---|
| **Epic** | A spec, or a wave spanning several | A container. **Never commit against one.** |
| **Issue** | One meaningful unit someone would want to read about | What a commit names |
| **Subtask** | A step inside it — a checklist line, in its parent's project | Cheap to add, ticked off, no ceremony |

**Prefer fewer, meaningful issues with subtasks** over many tiny issues. Splitting work
apart just to have something to reference is bureaucracy; the subtask list is where the
steps belong. If two "issues" turn out to be one component, that was over-decomposition
— say so on the issue rather than closing both quietly.

### The loop

1. **File it before building.** A one-line ask ("fix the board scroll") is still an
   item. Small is fine; absent is not. Put it In Progress when you start.
2. **Commit with the key in brackets**: `[RADD-412] board columns scroll instead of
   clipping`. **One commit per issue.** The bracket form auto-links — the connector's
   key regex matches inside brackets — so the commit appears in the issue's Version
   control tab with no extra step. Never hand-add a VCS link for something the
   connector will find.
3. **Move it to `Waiting for release`** when the work lands. It is finished, it has not
   shipped; that state is in the `done` category, so throughput counts the day the work
   was done.
4. **A release sweeps it to Done** with the version recorded — automatically from a
   published GitHub release (the GitHub connector, RADD-1129), or
   `POST /releases/{id}/sweep` by hand.
5. **Plans** (a spec, a multi-session wave) are an epic with its children filed up
   front. The plan lives in the tracker, not only in `PLAN.md`.

### Descriptions and comments

An issue whose body is one sentence is not filed, it is mentioned. Write what someone
who was not there needs:

- **What is wrong or wanted**, with the evidence — the actual symptom, the actual number.
- **What changes**, including the decision you made and the option you rejected.
- **Where** in the code.
- **Done when** — the observable condition, not "it works".

Comments follow the same bar. "Shipped in 0.3.0" is a receipt, not a comment; say what
shipped, what it cost, and what you found on the way. If something surprised you while
building — a bug the type checker could not catch, a design that had to be merged rather
than added — that belongs on the issue, because it is the part nobody can reconstruct
later.

### Logging time

A session with Hussein is his working time, so it is logged against the issues it
produced — when work ships, not as a separate chore.

**Derive it; never estimate it.** The session's own artefacts are timestamped: the
scratchpad directory says when it started, `git log` gives a boundary per issue, and
`now` ends it. Allocate the stretch before each commit to the issue that commit names,
split evenly when a stretch covers several.

Three rules that keep it honest:

- **Never log more than the session lasted.** Sum the entries and check against the
  span; trim the largest if it overshoots. An allocation that exceeds wall clock is a
  fabrication with arithmetic on top.
- **Say what it is in the note** — elapsed wall clock is an UPPER bound on attention,
  not a measurement, and the note should admit that.
- **Attribute it to the person, not the agent.** `author_id` on the worklog needs
  `project.manage`, which is one of the documented reasons to use the owner key.

Categories: `Development`, `Documentation`, `Testing`, `Investigation`, `Code Review`.

### Attribution

**Attribution is the owner (RADD-694, decided 2026-08-02, superseding the earlier
agent-by-default rule):** every tracker write — issues, comments, transitions,
releases, worklogs — is made with the owner's key and appears as the person.
One person, one key; no per-person service accounts. `SYSTEM_ACTOR_ID` remains
for genuinely automated flows (webhook sweeps, connector links), which are not a
person's writes. The spec-113 scoped-key machinery stays for external/CI agents;
this project's own workflow simply doesn't use it.

### MCP first (RADD-693)

The instance embeds an MCP server built for exactly this work (specs 45/114);
`.mcp.json` registers it once as **`radd`**, with the owner PAT in
`RADD_API_TOKEN`. **Work the tracker through those tools.** REST is the fallback
for what the MCP surface cannot yet express — and every such fallback is an MCP
gap: say so when you take it, and file it (that habit is how RADD-672 and
RADD-673 were found). Since 0.4.0 the whole loop — file with type/parent/points,
transition, comment, log categorized time, create a released version, sweep —
runs over MCP with zero REST calls, and the actor being the worklog author is
what makes time attribute correctly with no extra parameter.

The operational side — which token, which endpoint, the snippets — is in the local
`track` skill (`.claude/skills/track/`), which carries machine-specific paths and is
therefore not committed.

## Frontend conventions (post-modernization)

- **Use the semantic tokens, never raw palette utilities.** `web/src/index.css` defines surfaces `bg-base/surface/elevated/overlay`, neutral borders `border-subtle/strong/emphasis` (weakest → loudest), text `text-heading/fg/fg-secondary/fg-muted/fg-faint`, accent `bg-accent`/`bg-accent-hover` (fills) + `text-accent-text`/`text-accent-text-strong` (accent as legible text) + `outline-focus` (every focus ring), `shadow-lift/pop/modal`, `animate-fade-in/overlay-in/menu-in`. **`web/src` contains zero raw `zinc-*`/`indigo-*` utilities — keep it that way**; a raw palette class in new code is a review finding (the remap underneath is what makes light/dark work — don't bypass it with hardcoded hex either). One deliberate exception: text sitting on a fixed non-themed fill (e.g. roadmap category bars) uses `text-black`, which must NOT invert. (`rich-editor.css` used to be a second exception, reading `--color-zinc-*` to retint Milkdown/Crepe's own scale — RADD-754 removed the retint with the dependency, and the file is now semantic tokens throughout.)
- **The accent is its own per-theme scale** (`--accent-fill/-hover/-text/-text-strong/-focus` on `html` and `html.light`), not part of the zinc/indigo remap — that's what lets a filled accent lighten on hover in dark and darken in light. The plugin SDK's `--radd-accent*` tokens point at these, so keep the two in sync (`web/packages/plugin-sdk/src/styles/tokens.css`).
- **Use the kit.** `Button` (variants+sizes), `Select`/`SelectField`, `DropdownMenu`, `Modal`, `TextField` in `web/src/components/`; `ConfirmDialog` (`useConfirm`), `Table`, `TokenMultiSelect`, `CollapsibleCard` (collapsed-by-default card with count chip — reference-material sections), `EmptyState`, `IconButton`, `ErrorText`, `Switch`, `Pager` and the date helpers from `@radd/plugin-sdk` — import them from the SDK, never through a host re-export (RADD-1375; a boundary test refuses one). Native `<select>`, `window.confirm`/`alert`, and hand-rolled action buttons are banned.
- **Core plugins' UI is bundled, optional plugins' UI is a remote (RADD-1373).** A core module's UI lives in `<module>/ui/src` and contributes through slots like any plugin, but the host bundles it and registers it at boot — no loading gap. The host imports a plugin's types/contracts only through its package exports (`@radd-plugin-ui/<plugin>/…`), never by relative path into `server/src`.
- Builds run without npm: `cd web && ./node_modules/.bin/tsc -b && ./node_modules/.bin/vite build`.

## Query language (SLQ) — two dialects, one language

- **A dialect is rooted at the entity it RETURNS.** Items for `/items`, worklogs for the timesheet. That is not style: an item-rooted query cannot express `issue IS EMPTY`, because it returns items and a general worklog has none. If a new surface needs filtering, ask what its rows are before adding fields anywhere.
- **Fields are bare; the root is implicit.** `author`, not `worklog_author`; `issue`, not `item_id` — SLQ names concepts, not columns (it says `assignee`, never `assignee_id`). A prefix is only correct when reaching sideways from another root (`logged_by` on the item dialect).
- **Reach across entities by DELEGATING, never by restating.** `issue.<field>` hands the condition to the item compiler; a second copy of the item field catalog would fork and drift. Delegation is exact for to-ONE relations (per-condition == subquery). Only a to-MANY relation would need real sub-queries, for same-row conjunction — still unbuilt.
- **The two directions use different seams, and the dependency stays one-way.** item→other: the plugin `SlqFieldSpec` registry, so `items` stays ignorant. other→item: a direct call to `items.slq.compile_query` (a public service function) from a module that already `depends_on` items.
- The lexer, parser and coercion helpers are **generic query machinery** exported from `items.slq`. They belong in the kernel eventually; don't copy them.

## Verifying UI work

Building is not verifying. This session shipped three bugs a clean `tsc` + `vite build` could never have caught — a flex container that squashed 92 cards into 12px strips, a collapse that toggled `aria-expanded` while staying 288px wide, and board columns that clipped 75 cards to five. Each looked right in the diff.

- **Look at the rendered output**, and prefer measuring it to eyeballing it. `web/scripts/lib/cdp.mjs` (`openBrowser`, `login`, `waitFor`, `report`) is the harness every proof uses: headless Chromium over the DevTools Protocol, Chrome from `~/.cache/ms-playwright`, one profile per run removed on close; a screenshot plus `getBoundingClientRect`/`getComputedStyle`/`scrollHeight` probes settles most questions in one run.
- **Contrast and palette are computable — compute them.** State/chart colours go through the dataviz six-checks; text needs 4.5:1 where a fill needs 3:1, which is why `--chart-*` has a separate ink tier.
- Screenshots at reduced scale lie about small UI. Twice this session a pill looked wrong and the computed styles were correct.
- **Headless Chrome reports `(hover: none)` and `(pointer: none)` at BASELINE**, and Tailwind v4 gates every `hover:`/`group-hover:` utility on `@media (hover: hover)`. So hover-revealed chrome is not styled at all in a proof: `:hover` matches, the class is present, the compiled selector matches, and the computed style is still the un-hovered one — which reads exactly like a product bug. `web/scripts/lib/chrome.mjs` carries the `--blink-settings=primaryHoverType=2,…` flag and every proof asserts `matchMedia("(hover: hover)")`.
- **A leaked browser is worse than a stale bundle.** A proof that finds something already listening on its debug port connects to a browser from an EARLIER run, launched from different code with different flags; every assertion then describes something this run never configured. `openBrowser` refuses to start in that case.
- **ProseMirror resolves a node view by FIRST match.** That decided behaviour three times in one wave. Whenever a node view "does not apply", check what else registered one before it.
- **`contentRef` APPENDS the adapter's content element; it does not become the element you put it on.** `@prosemirror-adapter/react` builds that element from `contentAs`, which defaults to a `<div>` — so `<tbody ref={contentRef}>` nested a div inside the tbody, every `<tr>` landed in it, and the rows formed their own anonymous shrink-to-fit table: 20px cells under 213px columns, with the right row count, the right text, and a colgroup (RADD-759). Pass `contentAs` whenever the content element's TAG matters.
- **A node view whose body is a form needs `stopEvent`**, or ProseMirror reads every keystroke aimed at an input as a keystroke on the document. Scope it to your own chrome (`closest("[data-…-chrome]")`) so clicking the content still selects the node.
- **Starlette matches routes in DECLARATION order.** A literal `/x/<word>` declared after `/x/{id}` is unreachable — it registers, appears in the OpenAPI schema and at `/docs`, and answers a 422 about parsing the word as a UUID (RADD-761). `tests/test_route_shadowing.py` asserts this for the whole app. Note that a scan over `app.routes` sees mostly `_IncludedRouter` wrappers whose `path` is `None` — walk `effective_candidates()`, or the check passes on a broken tree, which is how its first version did.
- **A wire constant is a contract with no compiler behind it.** A renamed enum value or moved route path is silently broken on the client: it type-checks, it builds, and the feature just does nothing. When renaming a subsystem "internals included", grep the SPA for the OLD vocabulary and probe the endpoints it actually calls — RADD-701 left four (`doc_page`, `/docs/search`, two `/public/kb/*`), and each was a dead feature nobody had used that day.
- **Unlayered CSS beats every Tailwind utility**, regardless of specificity — a third-party `reset.css` outranks anything in `@layer utilities`. It is why a 24px affordance was once a 13×13 target.
- **A test that passes vacuously is worse than one that fails.** Two in this wave: a check skipped because its fixture was missing, and an assertion that was already true before the change landed. **A check that fails PERMANENTLY is read the same way** — `editor-style-baseline.json` recorded RADD-759's squished 30px table cells as the reference and went unrecorded for two commits, so the proof reported a regression on every run and would have hidden a real one (RADD-767).
- **Chrome anchored to the SELECTION disappears when there is no selection.** The AI progress indicator was positioned at `selection.left - 110`; a document-wide run (the toolbar button, the read-mode hand-off) carries no selection, so it painted at `x: -110` — present, correct, and off the left edge. It read as "the AI gives no feedback at all" for a year of that feature's life. Ask what a surface is a property OF before deciding what it hangs from (RADD-762).
- **A floating panel has nowhere to go when the editor fills the viewport.** The replacement was first anchored to the editor's bottom-right and clamped on-screen; the screenshot showed it sitting on top of two of the three paragraphs of the diff it was asking about, and no offset fixes that. Chrome that describes the document belongs IN the editor's chrome, where it takes layout space instead of borrowing it — which also deletes the measurement, the clamp and the scroll listener.
- **Dim is not the same as quiet.** Making per-block review buttons less shouty by dropping opacity would have put their text under 4.5:1. Removing the CHIP (fill + border) at rest and restoring it on hover/focus keeps the text colour — and therefore the contrast — untouched.
- **Chrome keeps only 250 resource-timing entries**, so a "not loaded" check over a page that fetches ~210 chunks passes vacuously until the buffer is raised; `web/scripts/lib/cdp.mjs` raises it (RADD-1343 wave).
- **A proof harness that leaks a Chrome profile per run fills `/tmp`** (a tmpfs) after a few hundred runs, and Chrome then hangs instead of failing; `lib/cdp.mjs` removes its profile on close (RADD-1399).
- **Two agents each adding `integrations=` to one manifest merge textually clean and fail to import** (a duplicate keyword argument is a SyntaxError the merge cannot see).

## Running

**Two one-command local stacks (RADD-1025).** They use SEPARATE databases and
separate Garage volumes, so switching between them costs nothing and neither can
touch the other's data:

```bash
sh scripts/dev.sh          # your working data (db :5455, garage :3900/:3910)
sh scripts/dev-clean.sh    # an EMPTY instance (db :5457, garage :3920/:3930)
sh scripts/dev-clean.sh --keep   # …and again, without wiping it
```

Clean means no DATA, not no configuration: it comes up with both storage hosts
registered and the routing chain in place, the RADD_SEED_LLM_BASE_URL chat/vision provider (set it in .env; unset skips that wiring),
TEI holding embeddings, every AI feature toggle on, and an admin to sign in as —
all of which are DB rows, so a bare `alembic upgrade head` leaves them dark.
`server/scripts/seed_dev_stack.py` is that wiring and is idempotent.

```bash
# Everything in the container (recommended — brings pg_dump/pg_restore, which the
# app now REQUIRES at startup; ./server is mounted, so edits live-reload):
podman compose -f compose.dev.yaml up      # db + API on :8000

# Or host-run, Postgres in a container (needs a local Postgres client, or
# RADD_BACKUP_TOOLS_OPTIONAL=true to start without a working backup system):
podman compose up -d db          # Postgres 16 on localhost:5455 (from repo root)
cd server
uv sync
uv run alembic upgrade head
uv run python -m radd.seed --email admin@example.com --password change-me --name "Dev Admin"
uv run uvicorn --factory radd.app:create_app --host 0.0.0.0 --port 8000
# full app (web UI + API): http://localhost:8000 — docs at /docs. Log in with the seeded creds.
uv run pytest                    # self-contained: re-creates + migrates a throwaway `radd_test` DB (override: RADD_TEST_DATABASE_URL); the dev DB is never touched
# Jira sample import (issues keep their real Jira IDs 1:1):
#   uv run python scripts/import_jira.py --file scripts/sample_data/jira_sample.json --email ... --password ...
# frontend dev: cd web && npm run dev (port 5173; npm run build refreshes the bundle served at :8000)
```

**Demo scripts are gone (RADD-1082):** the nine `scripts/demo*.sh` walkthroughs had been broken since the spec-86 workspace eradication (they POSTed `/workspaces`) and were deleted rather than rewritten — `pytest` covers regression, the synthetic sample data covers "show me the product with data in it".

Migrations after model changes: `uv run alembic revision --autogenerate -m "..."` (review the generated file), then `upgrade head`. Parallel agents may create sibling heads — merge with `alembic merge`.

## Releasing & deploying (the live instance)

Radd runs itself in public at **project.radd-hq.com**; the code lives at
**github.com/radd-hq/radd** (canonical since RADD-1130) and the private deployment repo
on the self-hosted Forgejo at **git.radd-hq.com**, which also keeps a read-only mirror of
the app repo. Contributor-facing setup, conventions and PR rules: `docs/contributing.md`.

**Two repos, two pipelines, and they are not interchangeable.** This repo builds an
IMAGE; a separate private deployment repo decides WHICH image runs. Tag a version here
(`git tag -a v0.2.0 && git push origin v0.2.0`) → CI publishes
`ghcr.io/radd-hq/radd:0.2.0` → bump `image.tag` in the deployment repo → CD runs
`helm upgrade`. There is **no `latest` tag**: deployments pin an immutable version, so a
rollback is editing that value back, not a race over what a moving tag points at.
**The release pipeline runs on GitHub Actions (RADD-1128):** `.github/workflows/publish.yaml`
reuses `checks.yaml` as its `test` job (pytest, ruff, tsc, vite, plugin builds, Chromium
smoke), builds the image with `RADD_VERSION` from the tag, pushes to ghcr.io, then
publishes the GitHub release with notes (`scripts/release_notes.py`), the SBOMs and the
vulnerability reports (`release_assets.py`, `sbom_page.py` — host chosen by
`scripts/release_host.py`). Pull requests get the same checks on GitHub's disposable
runners; nothing with credentials runs fork code.

**Never change the cluster by hand.** `kubectl edit` in production is reverted the next
time CD runs; the deployment repo is the source of truth. The end-to-end procedure —
pre-flight checks, the failures that have actually happened, and rollback — lives in the
`release` skill (`.claude/skills/release/`, local only: it carries machine-specific paths);
the contributor-visible half is `docs/deploy.md`.

`main` is protected on GitHub (no force-push, no deletion, admins included). Every pull
request runs `.github/workflows/checks.yaml` on GitHub's disposable runners with a
read-only token — the safe place for fork code, which is why PR checks never existed on
the Forgejo runner that holds deployment credentials.

## Repo layout

- `server/` — Python 3.12+ / FastAPI / SQLAlchemy 2 backend (uv project); modules in `src/radd/modules/`
- `web/` — React 19 + TS + Vite SPA (built; `npm run build` output in `web/dist` is served by the API)
- `PLAN.md` — status (§8), design, decisions · `docs/modules.md` — module map (keep current) · `docs/specs/` — per-feature build specs (historical record) · `docs/contributing.md` — setup, conventions, PR rules · `docs/deploy.md` + `docs/deploy-k3s.md` — running it
- `compose.yaml` — app + dev Postgres (`Containerfile` builds the image; `deploy/helm/radd/` is the chart)
