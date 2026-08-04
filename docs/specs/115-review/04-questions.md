# Open questions put to Hussein

Asked 2026-08-04 at review time. Answers recorded below each question once
given; the execution plan references them as Q1–Q4.

## Q1 — What floor does an email-provisioned requester account hold?

RADD-828 as filed says "nothing but the Baseline". But the Baseline is the
*operator's staff policy row*, and this release deliberately doesn't narrow
it on the live instance — so enabling email ingest would hand every
stranger whatever the row says (today: full `item.read` + `page.read`).

- **A (recommended): a dedicated seeded `Requester` role** —
  `item.read@own` + commenting on own items; `UserSource.EMAIL` accounts
  get it instead of the Baseline. The internet-facing floor decouples from
  the staff floor permanently; no pre-flight dependency; still one role
  model.
- **B: the Baseline, as filed** — one floor for everyone; safe only after
  the Baseline is narrowed, so 828 becomes conditional on the Q2 act.

**Answer: A — dedicated Requester role.**

## Q2 — Does this release flip the live instance's Baseline row?

The brief forbade it ("the one thing that must NOT ship flipped") to
protect existing deployments — of which there is exactly one, yours. The
no-backcompat rule makes this a choice rather than a rule. The fresh-seed
becomes `item.read@own` either way; the pre-flight report ships either way.

- **A (recommended): the release flips it** — migration narrows the row to
  `item.read@own` and drops `page.read`; staff read access restored by one
  instance-wide role grant the same migration seeds. One clean break, and
  N5 (restricted spaces defeated by Baseline `page.read`) dies in the same
  release. You run the pre-flight report before tagging.
- **B: capability only** — you edit the row in Settings after reading the
  report. The brief's original shape.

**Answer: A — the release flips it.** The migration narrows the row to
`item.read@own`, drops `page.read`, and seeds one instance-wide staff role
restoring today's effective access for existing active users. The
pre-flight report is run before tagging. This supersedes the brief's
"must NOT ship flipped" section.

## Q3 — Which surfaces accept groups as subjects in this release?

Ten tables store `team_id` as a subject. Making groups first-class
everywhere multiplies UI, constraints and tests by ten.

- **A (recommended): the two grant tables only** (`global_role_grants`,
  `access_grants`). Leave, participants, form shares, comment visibility,
  cycle teams, SSO defaults, approval snapshots stay team-only —
  teams-holding-groups reaches all of them indirectly, and any of them can
  graduate later.
- **B: grants + comment visibility + participants** (the two most likely
  to want AD groups directly).
- **C: everywhere teams are accepted.**

**Answer: A — the two grant tables only.** Everything else stays
team-only and documented; graduation is per-surface, later.

## Q4 — Do hardcoded author-own rights become seeded `@own` grants?

Today "author deletes own comment/worklog" is hardcoded, which is why F4's
verb confusion exists and why the inspector can't explain those rights.
Relations make the honest form expressible.

- **A (recommended): fold them in** — seed `comment.delete@own`,
  `worklog.delete@own`, `attachment.delete@own` into the Baseline in the
  same migration that normalises verbs; delete the hardcoded author
  checks. Every refusal becomes grant-explainable (D1's principle), and an
  operator can now *revoke* own-deletion, which is inexpressible today.
- **B: keep the hardcoded exemptions** — smaller change, but the verb
  cleanup ships with a known class of unexplainable access, and the
  inspector lies by omission about it.

**Answer: A — fold them in.** Seeded `@own` grants replace the hardcoded
author checks in the verb-normalisation migration.
