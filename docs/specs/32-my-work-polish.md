# Spec 32 — "My Work" home + Tier-3 polish

Tier-3 items from `docs/roadmap-ideas.md` that punch above their weight, shipped as
small slices:

## 1. "My Work" home (`/`)

The landing page becomes a personal dashboard (the projects index moves to
`/projects`; the sidebar and palette point there). Sections, each one SLQ query
(`GET /items?q=` — no new backend):

- **Assigned to me** — `assignee = me AND category NOT IN (done, canceled)`.
- **Due soon** — same scope with `target <= <today+7d>`, client-sorted by target
  date, overdue rows tinted red (the roadmap's "overdue surfacing").
- **Starred** — `starred = true`.
- **Inbox preview** — the 5 newest unread notifications + a link to `/inbox`.

Rows open the issue peek panel (spec 25) so you stay on the dashboard.

## 2. CSV export of any saved view

A **Download CSV** button on saved-view pages exporting the CURRENTLY FETCHED
items (client-side; inherits the 200-item page cap): key, title, state, category,
kind, priority, assignee, reporter, team, labels, cycle, release, start/target
dates, created/updated. Proper quoting; filename from the view name.

## 3. `/` opens the command palette

Pressing `/` outside an input/textarea/contenteditable opens Cmd-K (spec 28) —
the first slice of keyboard-first nav.

## Deferred from the Tier-3 list (want their own specs)

- Light theme + density toggle (a theming pass across every hardcoded palette class).
- Item archive/DELETE (audit-trail + child/FK semantics need care).
- Board WIP limits, issue templates, sub-task checklists, comment reactions.
- Story points: representable TODAY as a `number` custom field; a builtin field is
  only worth it when velocity should count points instead of items.
- j/k/e/a/x list navigation (needs a focus model across list surfaces).
