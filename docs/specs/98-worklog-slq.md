# Spec 98 — Worklog SLQ, and the delegation that keeps it small

Phase 2 of relational querying (spec 97 was `logged_by`/`commented_by`). The
timesheet gets a filter bar over WORKLOGS.

## Why a second dialect and not more item fields

The timesheet's rows are worklogs. An item-rooted query returns items, so it can
never surface a **general worklog** (spec 59) — there is no item to return. That
is a correctness limit, not an ergonomics one: no number of `worklog_*` fields
bolted onto the item dialect makes `issue IS EMPTY` expressible there.

The two dialects answer genuinely different questions and both are wanted:

| Root | Question | Where |
|---|---|---|
| Item | *which issues* have this kind of time on them | `logged_by = alice` (spec 97) |
| Worklog | *which hours* match this | the timesheet |

## Naming: the root is implicit

Worklog fields are bare — `author`, `category`, `worked_on`, `time`, `note`,
`project`, `issue` — because item queries say `priority`, not `item_priority`.
Prefixes (`worklog.author`, `worklog_issue`) would be noise on every term, and
`item_id` was rejected in favour of `issue`: SLQ names concepts, not columns
(it already says `assignee`, never `assignee_id`).

## The delegation

`issue` has three forms:

```
issue IS EMPTY        -- general worklogs
issue = DEV-123       -- a specific issue by key
issue.<anything>      -- handed to the ITEM compiler
```

The third rewrites the condition onto the item field and calls
`items.slq.compile_query`, wrapping the result as
`worklog.item_id IN (SELECT id FROM work_items WHERE …)`.

This is the whole reason the dialect is small. Restating the item field surface
here would have forked it and let it drift; delegating inherits builtins, custom
fields (`issue.cf.render_farm`), ancestors, labels and plugin fields — including
spec 97's `issue.logged_by` — permanently and with nothing to sync.

**It is exact, not an approximation.** A worklog has exactly one issue, so
delegating PER CONDITION and combining at the worklog level selects the same
rows as a nested subquery would. That is what retired the `{ … }` grammar we
had considered: braces are only needed for same-row conjunction over a to-MANY
relation, and this relation is to-one.

Autocomplete delegates by the same trick: splice `issue.` out of the query, ask
the item suggester, shift the returned offset back by the prefix width. So
`issue.assi` completes from the item dialect's field list and
`issue.assignee = ` from its value resolvers (`me`, `none`, real users).

## Isolation

Both directions use their proper seam, and the dependency stays one-way:

- **item → worklog** (`logged_by`): the plugin `SlqFieldSpec` registry — items
  stays ignorant of worklogs.
- **worklog → item** (`issue.*`): a direct call to `items.slq.compile_query`, a
  public service function. `timelogging` already declares `depends_on=(… items)`.

The lexer, parser and coercion helpers are generic query machinery — nothing in
them knows about work items — and are now exported from `items.slq` so a second
dialect is a compiler plus a catalog rather than a second copy of the language.
Longer term they belong in the kernel; that move is deferred, not forgotten.

## Safety

`q` is compiled in the router and ANDed onto the scope filters inside
`timesheet.build(where=…)`. It can only ever NARROW what the actor is already
entitled to see — the timesheet.view / own-time-only rules are applied before
it and a query cannot reach past them.

## Examples

```
author = me AND issue.assignee != me           -- my hours on other people's issues
issue IS EMPTY AND category = "Code Review"     -- unattributed review time
issue.category = done AND worked_on >=
time > 4h                                       -- long single sessions
note ~ merge
```

## Tests

`tests/test_worklog_slq.py` executes compiled queries against real rows — a
wrong predicate returns a plausible set rather than an error. Covers general
worklogs, author-vs-assignee, delegation (including that general rows never
match an issue-scoped predicate), the scalar fields, and positioned errors on
both sides of the delegation.

## Deferred

- **Braces / sub-queries.** Retired for this direction; still the only way to
  express same-row conjunction over a to-many relation (`worklogs { author =
  alice AND worked_on >= … }` on the ITEM dialect).
- **ORDER BY** in the worklog dialect — the timesheet imposes its own ordering.
- Moving the lexer/parser/helpers into the kernel.
