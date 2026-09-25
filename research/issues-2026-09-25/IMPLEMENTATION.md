# GitHub requests agreed September 25, 2026

| GitHub | Radd | Implementation |
| --- | --- | --- |
| [#25](https://github.com/Radd-HQ/Radd/issues/25) | [RADD-1333](https://project.radd-hq.com/issues/RADD-1333) | Searchable Unicode emoji/symbol picker in the shared rich editor. |
| [#27](https://github.com/Radd-HQ/Radd/issues/27) | [RADD-1334](https://project.radd-hq.com/issues/RADD-1334) | Private, server-persisted My Work widget definitions; personal activity; shared dashboard editing and drag sizing. |
| [#28](https://github.com/Radd-HQ/Radd/issues/28) | [RADD-1335](https://project.radd-hq.com/issues/RADD-1335) | Independent resolution-aware discussion expansion and readable reply controls; composers open on Reply. |
| [#29](https://github.com/Radd-HQ/Radd/issues/29) | [RADD-1336](https://project.radd-hq.com/issues/RADD-1336) | Collapsible My Work widgets, saved across browsers; expanded dimensions retained. |
| [#30](https://github.com/Radd-HQ/Radd/issues/30) | [RADD-1337](https://project.radd-hq.com/issues/RADD-1337) | Reversible signature annotations, ordered domain regex rules with preview, conservative built-ins, optional AI fallback. |
| [#31](https://github.com/Radd-HQ/Radd/issues/31) | [RADD-1338](https://project.radd-hq.com/issues/RADD-1338) | Linked comment highlight lasts ten seconds after landing and cleans up on navigation. |

## Behavior

My Work starts with Assigned to Me (open, in-progress first), Due Soon (including overdue), My Activity, Inbox, and Starred. Existing approval/request/form activity adds the relevant default widgets. Every personal widget remains available from the picker, together with existing reports and configurable issue widgets. Saved customization overrides future shipped defaults. Reset stages the current suggested default; Cancel discards it.

Both dashboard surfaces use twelve columns with pointer movement and width/height resizing, keyboard order and dimension controls, mobile stacking, and scrollable content. Movement, sizing, configuration, removal and additions require Customize mode. Save persists the whole definition atomically and checks the version the editor started from. Personal collapse changes persist outside edit mode. Shared dashboard readers can collapse cards locally without changing the shared layout. Original widths in thirds migrate to equivalent twelfths.

Personal activity fixes the actor to the caller, excludes automation actions, and rechecks current item/comment access. Responses contain action labels and readable issue keys, not historical payloads or restricted field values. Project/date filters and cursor pagination are available.

Email signatures are annotations on original bodies, never destructive rewrites. Rules match exact sender domains unless subdomains are enabled; regex matching is case-insensitive and multiline. The matching text starts the signature. Patterns and input sizes are bounded, and matching has a time limit. Built-ins follow custom rules; AI runs last only when its feature is explicitly enabled and the configured chat provider is callable. AI returns an exact suffix, with no rewriting or tool use. Model failure leaves the message visible. Sender-authentication warnings remain visible outside annotations. Editors can clear an annotation with Not a signature; original content remains even if raw MIME retention is disabled. Older tickets are not retroactively processed.

Emoji and symbols are ordinary Unicode characters. MCP clients can include characters such as ✅, ❌, ⚠️, ℹ️ and ❓ directly in existing issue description, comment body, and wiki Markdown body arguments. No new MCP command or icon syntax is needed.

## Deployment

New migrations: `d1335widgets` and `d1336signatures`. They follow the earlier review migrations already in this working tree. AI signature detection defaults off. The Python `regex` dependency supplies bounded matching. No application database migration or deployment is performed by local verification.

## Verification

- Backend full suite: **3,138 passed, 4 skipped**. A subsequent dashboard locking correction passed all 24 focused dashboard/feature tests.
- Frontend unit tests: **33 passed**.
- TypeScript and production build: passed for the host and all eight plugin UI remotes.
- Chromium checks: feature interactions, resolvable threads, wiki comments, and app smoke passed. The feature check covers independent threads, reply readability, composer opening, ten-second highlight, Unicode insertion, edit-only pointer resizing, Cancel, Save, and collapse persistence.
- Ruff passed for all changed Python files; diff whitespace checks passed.

The work is committed locally. Existing unpublished commits precede this wave; no push, release, application migration, or deployment was performed. Radd completion state is Waiting for release. GitHub reports remain open pending publication, with implementation and validation responses.

Dashboard customization and collapse (#27 and #29) share one canvas component and one commit; separate implementations would duplicate persistence and sizing behavior. Regression tests for the six requests live in `server/tests/test_github_issue_features.py` and `web/scripts/browser-issue-features.mjs`.
