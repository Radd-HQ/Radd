# Spec 60 — Team-restricted cycle visibility + collapsible sidebar

**Status: built.**

## Problem

Every cycle was visible to everyone, and the sidebar force-fed all of it: every
cycle in the workspace, every project fully expanded (untenable at 20 projects),
no way to fold sections you don't care about.

## Cycle visibility

- `cycle_teams` join table (migration `8325cd80bd6d`): **no rows = public**
  (today's behavior), rows = visible only to members of those teams.
- `CycleRead.team_ids` ([] = public); `CycleCreate.team_ids` /
  `CycleUpdate.team_ids` ([] on update = make public again; omitted = unchanged).
  Foreign teams 409 on write.
- Enforcement: `GET /cycles` filters through `service.visible_cycles`;
  `GET /cycles/{id}` and `/stats` 404 on hidden cycles (`cycle_visible_to` —
  don't-reveal-existence, mirroring view sharing). Every consumer of the list
  endpoint (sidebar rail, planning sections, cycle pickers, bulk move) inherits
  the filter for free.
- **Bypass = workspace admins (`workspace.manage`), deliberately NOT
  `cycle.manage`** — every member holds cycle.manage (spec-36 floor), which
  would make restriction a no-op. Members who manage cycles still only see
  public + their own teams'.
- Not covered (documented): the cycle NAME still shows on items assigned to a
  restricted cycle (item chips/history hydrate from item data), and SLQ
  `cycle = X` still matches items — this is item-level data; restricting it is
  field-rules territory.
- UI: the cycle modal (settings → Cycles) gained a "Visible to" team checkbox
  list ("Public — everyone…" vs "Only members of the checked teams…"), and
  restricted rows show an amber **Restricted** chip.

## Sidebar

- **Foldable sections** (spec 60): Views / Docs / Cycles / Projects headers get
  a chevron; collapsed state persists in localStorage (`radd.sidebar`). Docs'
  label still navigates; the chevron folds.
- **Project trees default COLLAPSED** — one row per project. The current
  route's project auto-expands; explicit expand/collapse overrides persist
  (`expandedProjects` / `collapsedProjects`, the latter beating auto-expand).
- Cycles rail content is now the server-filtered visible set.

## Verified

`tests/test_cycle_visibility.py` (public/team/manager matrices, single-cycle
guard, un-restrict round-trip, foreign-team 409) — suite 648 green; live HTTP
round-trip (restrict → admin bypass → public again); sidebar screenshot: DEV
folded to one row, TD auto-expanded on its route, fold chevrons on all sections.
