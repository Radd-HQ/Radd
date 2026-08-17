# Codebase scan — findings for later review

> **Historical snapshot** (2026-07). Preserved as the input that shaped later
> fix waves; individual findings may already be fixed — check the tracker.

A read-only sweep. **No code was changed.** Every entry carries a file, a line
number and a snippet so it can be checked rather than trusted.

| File | Category | Entries |
|---|---|---|
| `01-missing-features.md` | Usability gaps in issue tracking and the wiki | 14 |
| `02-dead-surface.md` | Built, reachable by API, no way to use it | 6 + 2 |
| `03-deprecated.md` | Legacy paths and compatibility shims still carried | 9 |
| `04-architecture.md` | Kernel/module/plugin boundary violations | 4 findings, 69+6 sites |
| `05-comments.md` | Oversized, stale, or non-factual comments | 13 |

## Method

Mechanical where possible, so it is reproducible rather than an opinion:

- **Dead surface** — all 432 server routes extracted from `@router.*` decorators
  with their `APIRouter(prefix=…)`, then every distinctive literal path segment
  (>3 chars, excluding `api/v1/id/me/all/new/list`) checked against the whole of
  `web/src` **and** `web/packages`. A route is listed only when a segment
  appears nowhere in either.
- **Architecture** — every `from radd.modules.X.<sub> import` where `X` is not
  the importing module and `<sub>` is not a public seam (`service`, `types`,
  `schemas`, `__init__`), minus the CLAUDE.md spine exception
  (`auth.models.User`, `projects.models.Project`).
- **Comments** — contiguous `#` blocks ≥12 lines and docstrings ≥28 lines;
  separately, comments naming vocabulary the codebase has removed.
- **Missing features** — candidate features grepped for across `server/src`;
  listed only where the count is **zero**, so absence is measured rather than
  assumed.

## Confidence

Marked per entry:

- **measured** — the scan proves it (a count of zero, a segment absent, a line
  that exists).
- **inferred** — the scan strongly suggests it but the judgement is mine,
  usually about whether something is *wanted* rather than whether it exists.

Nothing here is a bug report. Several entries are deliberate decisions that
merely look odd without their history; where the code says so, this notes it.
