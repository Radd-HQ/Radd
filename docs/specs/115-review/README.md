# Spec 115 review — verification, amendments, and the corrected execution plan

**Date:** 2026-08-04. **Method:** every factual claim in
`docs/specs/115-access-control-audit.md` and the order in
`115-execution-prompt.md` was checked against the working tree by five
parallel read-only code audits (authz layer; access module + kernel; the
claimed live holes; the Groups blast radius; the leak-checklist seams), plus
a tracker cross-check of all 24 filed issues. No code was changed.

**These documents supersede the corresponding sections of the audit and the
execution brief where they conflict.** An executor starts here.

| File | Contents |
|---|---|
| [`01-corrections.md`](01-corrections.md) | What the audit got right, what it got wrong, and eight live defects it missed — with file:line evidence |
| [`02-decision-review.md`](02-decision-review.md) | D1–D14 assessed one by one; the simplifications the no-backcompat rule buys |
| [`03-execution-plan.md`](03-execution-plan.md) | **The corrected A→Z order** — amended steps, four new work items, the seam inventory, per-step verification |
| [`04-questions.md`](04-questions.md) | The four decisions that needed Hussein's answer, and the answers |
| [`05-nav-gating.md`](05-nav-gating.md) | NEW-E: the nav shows only what is useful to the actor — inventory of every nav surface, per-area rules, the shared-predicate mechanism |

## Verdict in one paragraph

The audit's *model* is sound: scope-on-the-grant (§5.1), relations (§5.4a),
deny (§5.4), and the Groups split (§5.6a) are the right shape, each is
inert-until-used or behaviour-preserving by construction, and the two-axis
factoring (scope × relation) passes the composition test. The audit's
*facts* are ~85% right and the misses matter: one of the three "confirmed
holes" points at the wrong endpoint (the hole is bulk **move**, which also
skips workflow guards — worse than reported), one is wrong about custom
fields but live for `description`, and **five additional cross-project read
leaks exist today** that no filed issue covered (timesheet, link/parent/epic
hydration, SLQ autocomplete, rollup descendants, an SLQ filter oracle).
The execution order is broadly correct — holes first, inspector second,
root-cause third, Groups before relations — but it under-specifies four
things the code demands: a `search_index` schema change **before** relations
can reach search, the creation (not reuse) of the item-resolution seam,
a per-item writability answer for the SPA once relations exist, and the
requester-account/Baseline coupling in RADD-828, which as filed ships a
default-open hole. Three tracker artifacts contradict the final decisions
and must be edited before handoff.

## The three load-bearing facts the plan can rely on

1. **`teams.user_team_ids` is a real single seam** — 20 call sites resolve
   membership through it. The subject graph lands there, once, memoised.
2. **Three shared query builders** (`items/service/listing.py:83`,
   `items/bulk.py:308`, `items/service/read.py:84`) carry lists, boards,
   counts, all six reports, and every MCP item tool. Relation `WHERE`
   injection is one edit each.
3. **The relation pattern already ships** in `forms/requests.py:65`
   (`visible_condition`) — the service-desk portal is §5.4a in miniature,
   trap-aware ("the trimming is in the QUERY, not the serializer"). It gets
   absorbed, not duplicated.
