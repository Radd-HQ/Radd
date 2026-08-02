# Spec 56 — Cycle regex filter on views + item↔cycle stint history

**Status: shipped** (round 16 of the polish thread).

## 1. Regex cycle filter on (planning) views

`views.cycle_filter` upgraded from a `*`/`?` glob to a full **regex**
(case-insensitive, unanchored): `^TS` pins the TS series, `PIPE|TS` shows
both, a bare `PIPE` still contains-matches. Validated with `re.compile` on
create/PATCH (`views/service._validate_cycle_filter` → 409); the client
matches with `new RegExp(pattern, "i")` (`view-utils.matchesCycleFilter`) and
degrades to match-all on a stored-then-broken pattern instead of blanking the
view. The ViewModal shows the field with live invalid-regex feedback + save
gating, and now ALWAYS shows it for `ViewType.PLANNING` (planning views are
implicitly cycle-grouped; previously the field only appeared when a cycle
axis was explicitly picked — so planning views couldn't set one at all).
Dialect note: patterns are compiled by Python on save and JavaScript at
render; stick to the shared subset (no inline `(?i)` flags, no possessive
quantifiers).

## 2. Item↔cycle stint history (the carryover trail)

**Why:** when a cycle completes and open items move to the next one, the old
assignment vanished — recoverable only from the event log, which is an audit
surface, not a query surface. Carryover is first-class planning data.

**Model:** `item_cycle_records` (cycles module, `history.py`) — one row per
VISIT: `item_id` (FK CASCADE), `cycle_id` (FK CASCADE), `added_at`,
`removed_at` (NULL = open stint). `work_items.cycle_id` stays the
current-cycle truth. Deleting a cycle CASCADE-drops its stints — complete
cycles instead of deleting them if history matters (this bit us: PIPE-116/117
were deleted, so their 294 event-log stints were unrecoverable).

**Recording:** items service calls `cycles.record_cycle_change` on every
cycle assignment change (create + update; the complete-cycle carryover routes
through update). Old open stint closes, new one opens; re-entering a cycle
opens a SECOND stint. Import creates stamp `occurred_at`.

**Read surfaces:**
- `ItemRead.past_cycles` — closed stints, deduped, oldest-first (batch
  hydration via `past_cycles_by_item_ids`); shown on the issue rail as a
  "Previously in …" chip row under the Cycle picker.
- SLQ `past_cycle` — equality/IN/none/IS [NOT] EMPTY over CLOSED stints
  (`past_cycle = "PIPE - 115"`, `past_cycle IS NOT EMPTY` = "has rolled over
  at least once"). The CURRENT cycle intentionally does not match — that's
  `cycle`. Autocomplete suggests cycle names; cheat sheet updated (and gained
  the previously-missing `cycle` row).

**Backfill:** migration `c536f26534fb` seeds open rows from current
assignments (added_at = item created_at); `scripts/backfill_cycle_history.py`
(dry-run default, `--apply`) mines closed stints from `item.updated` events'
`changes` diffs (cycle names → ids; deleted-cycle stints reported + skipped)
and sharpens the seeded open rows' `added_at` to the real entry time.

**Tests:** `tests/test_cycle_history.py` (record→move→clear→re-enter through
the items service + SLQ round-trip), `test_slq.py::test_past_cycle_field_compiles`.
