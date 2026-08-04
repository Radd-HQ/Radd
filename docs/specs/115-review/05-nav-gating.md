# NEW-E — the nav shows only what is useful to the actor

Requested by Hussein during review (2026-08-04): a user with no access to
worklogs should not see the Timesheet link; no readable project → no
Projects nav; no readable space → no Docs; cycles the same. Reduce clutter
wherever an area cannot be useful to the actor.

**Principle (spec-114 precedent): hiding is presentation, enforcement is
`authz.require`.** Nav visibility derives from server-answered facts; the
server never relies on it. Direct URLs to a hidden area still resolve and
still refuse properly — through RADD-836's refusal page, not a toast.

## What the scan found

The expanded Sidebar already gates about half its surface on data the
server scopes (readable projects, readable spaces, view/queue/cycle lists,
creatable projects for the New-item button; settings nav is thoroughly
gated). The problems are concentrated:

| Offender | Evidence | Defect |
|---|---|---|
| Fixed destinations: **Timesheet, Reports, Submission Portal, Projects** | `Sidebar.tsx:181-196` | Render unconditionally; no feature or access signal consulted |
| **Dashboards section + "New dashboard"** | `Sidebar.tsx:260-296` | Section always renders; create is ungated ("any member") |
| **The collapsed rail gates NOTHING** | `SidebarRail.tsx:44-48, 118` | A second copy of the nav with none of the sidebar's gates — the parallel-code-path defect class again |
| **Command palette Goto rows** | `CommandPalette.tsx:80-87` | Reports/Timesheet/Settings ungated |
| **Link pins replay stored URLs** | `PinsBar.tsx:159-168` | A pinned `/timesheet` outlives losing access to it (view pins already drop unresolvable ids — link pins should match) |
| Plugin nav `requires` checked with `perms.global` only | `Sidebar.tsx:71`, `settings/layout.tsx:286` | The RADD-810 scope-mismatch class, in nav |

## The mechanism: one predicate per area, defined once

A single **`useNavFacts()`** hook is the only source of area visibility,
consumed by Sidebar, SidebarRail, CommandPalette and the PinsBar link-pin
filter. Four surfaces, one truth — the rail can never drift from the
sidebar again. Facts come from two places:

1. **Derived from lists the shell already loads** (zero new requests):
   - `projects` → readable projects (`GET /projects`, already scoped)
   - `pageSpaces` → readable spaces (`GET /page-spaces`, already the
     Docs gate in the expanded sidebar)
   - views / dashboards / cycles / queues lists (already server-scoped)
2. **Two new server-computed booleans on the bootstrap payload**
   (`GET /auth/me` gains a small `nav` object) for areas with no client
   signal today:
   - `timesheet` — any readable project with time logging enabled, OR the
     actor has worklog rows (general/itemless worklogs exist, spec 59),
     OR `timesheet.view` held anywhere. Definition lives in ONE server
     function beside the timesheet's own authz.
   - `portal` — the actor's portal-form eligibility is non-empty (the
     server already computes this for `GET /portal/forms`; My Work's card
     already hides on empty).

After RADD-814, atom checks in nav go through the one `can(atom, scope)`
seam — which also fixes the plugin-nav `requires` scope mismatch.

## The per-area rules

| Area | Visible when | Notes |
|---|---|---|
| **My Work, Inbox, Search, Settings→Profile** | always | The floor. Nobody lands in a blank shell; a requester sees My Work with their requests. |
| **Projects** (destination + section) | readable projects ≥ 1 | Section already gates; the destination and rail/palette entries join it |
| **Timesheet** | `nav.timesheet` | See definition above |
| **Reports** (cross-project) | readable projects ≥ 1 | Per-project Reports rows already imply a readable project — unchanged |
| **Submission Portal** | `nav.portal` | Matches the My Work card's existing rule |
| **Docs/Pages** | readable spaces ≥ 1 ∨ `page.manage` | Already correct in the expanded sidebar; extend to rail/palette/pins |
| **Dashboards** | list non-empty ∨ can create | Mirror the Views-section rule; gate "New dashboard" on the dashboard-create atom (F6/CRUD gives it a real atom) |
| **Cycles** | list non-empty ∨ `cycle.manage` | Already correct; extend to pins |
| **Views** | list non-empty ∨ can create | Already correct (fix the `view.manage`→`view.create` gate in RADD-824) |
| **Settings** (footer) | always | Profile + tokens are universal; inner sections are already individually gated |
| **Plugin nav** | as today, but `requires` through `can()` | |
| **Link pins** | target area's predicate | A pin to a hidden area is dropped from render (kept in prefs — access can return), matching view-pin behaviour |

Settings inner nav and project-settings sub-nav are already gated
correctly (`settings/layout.tsx:262-268`, `project-settings/layout.tsx`)
— no change beyond the `can()` migration.

## Traps

- **The rail and the palette are the same nav.** Any gate that exists only
  in `Sidebar.tsx` is a defect; `useNavFacts()` is the fix *because* it is
  shared, not because it is clever.
- **Hide ≠ forbid.** No route guards are added; direct navigation to a
  hidden area gets the RADD-836 refusal page ("requires X at scope Y, ask
  Z"), which is strictly more useful than a link that was never there.
- **Don't gate on feature-flags alone.** Timesheet visibility is access ∧
  usefulness, not just "some project has timelogging" — a `timesheet.view`
  holder with no enabled project still needs the link for general
  worklogs.
- **Requesters are the acid test** (RADD-828): a `UserSource.EMAIL`
  account must see My Work, Inbox, its portal card — and no Projects,
  Timesheet, Reports, Docs, Dashboards, Cycles.

## Verification

Extend `restricted-access-proof.mjs`: for a requester-shaped actor and a
one-project member, assert each gated link is ABSENT from the sidebar,
rail, palette Goto list and pins — and PRESENT for the admin control run.
Each assertion proven to fail on pre-change code once (the vacuous-pass
rule).

## Where it lands in the order

Step 16b, immediately after NEW-D (per-item writability): it consumes
RADD-814's `can()` seam, and it must be in place before RADD-828 ships
requester accounts (the acid test above). Independent of Groups and deny.
