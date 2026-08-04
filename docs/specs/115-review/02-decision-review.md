# D1–D14 reviewed, and what the no-backcompat rule changes

Rule stated by Hussein 2026-08-04, during this review: **until V1 ships
publicly, backwards compatibility is a non-goal** — prefer losing/deleting
data over legacy backports, aliases, or compat ceremony. Migrations that
prevent hard 500s are correctness, not compat, and stay.

## Sound as decided — execute as written

- **D3** (project admins assign existing roles) — clean, `member.*` atoms
  exist, the missing part is a screen + the delegation check.
- **D6** (`@own` = reporter) — right call. One consequence to document,
  not fix: editing `reporter` *moves* row-level visibility with it. Under
  `item.read@own`, an agent reassigning reporter hides the ticket from the
  original requester. That is the designed meaning of a reassignable owner.
- **D11** (new resource types default closed) — one-line change, correct.
- **D12** (presets + sentence builder) — right UI shape; keep the v1
  preset list short and let the sentence builder carry the tail.
- **D13** (`@team` = `item.team_id`) — correct and the only inspectable
  definition. Verified: SLQ's `team` field, board team-axes, and cycle
  teams all already mean the item's own team, so the vocabulary agrees.

## Sound with amendments

- **D1 (admin bypasses, manager doesn't).** Two wording fixes from the
  code: (a) the `has_manage` bypass exists only in the flag model —
  views/dashboards resolve ownership separately and D1 changes nothing
  there; (b) "instance admin bypasses everything" has one deliberate
  exception that must survive — a spec-113 scoped API key narrows an
  admin's effective set (`authz.py:291-304`). D1's release-note line
  ("some project-manager flows start refusing") is confirmed real: after
  removal, a restricting field grant binds managers unless it names them.
  That is the intent; no parity-seeding, no softening.
- **D2 (Baseline → `item.read@own`).** The capability/act split survives
  review. What the no-backcompat rule changes: flipping the live
  instance's row in the same release stops being forbidden and becomes a
  choice (→ `04-questions.md` Q2). The pre-flight report (RADD-825) stays
  either way — it is the impact-preview feature (U4), not ceremony.
- **D4 (renames rewrite stored data).** Simplify: one destructive
  migration per rename wave (roles JSONB + `api_tokens.scopes` +
  `access_grants`), no runtime auto-rewrite machinery, no per-change event
  ceremony. The rewrite itself is correctness (stale atoms 500
  `GET /roles`). The RADD-701 pattern applies at migration time only.
  Plugin-uninstall keeps a runtime sweep (RADD-818) because uninstall is
  not a migration.
- **D5 (Groups).** The model is right and `user_team_ids` being a true
  single seam makes it executable. Amendments from the blast-radius audit:
  - **Subject-surface scope for v1 needs bounding** (→ Q3): ten separate
    tables store `team_id` as a subject. Recommended v1: groups become
    subjects of the two *grant* tables only; every other team-subject
    surface (leave, participants, form shares, comment visibility, cycle
    teams, SSO defaults, approval snapshots) stays team-only, documented —
    teams-holding-groups reaches those indirectly.
  - **Group-expanded members count as members** for stewardship, leave and
    approval electorates. This is not optional: post-migration every
    directory team's people are reachable only via its group, so excluding
    them would break today's behaviour for every AD team.
  - `SubjectContext.group_ids` must be a **required** field (no default) —
    six construction sites, and a defaulted field turns each missed one
    into a silent access denial instead of a compile error.
  - The memo lands **before** the CTE: `user_team_ids` is already called
    twice per batched resolution (`authz.py:373,377`).
  - Depth-limit truncation **fails closed**, stated beside
    `baseline_permissions`' same rule (`authz.py:202`).
  - The headcount ("resolves to 214 people") is a third query shape
    (group→users reverse CTE) — its own endpoint, batched for pickers.
  - `MemberSource` retires with `TeamSource` (a fifth retirement the spec
    doesn't list); `TeamChange`'s six directory event values retire with
    no reader-side alias (no-backcompat: old audit rows render degraded).
- **D7 (deny precedence).** Sound, but "narrower scope wins; at equal
  scope deny beats allow" is prose, not semantics. Before RADD-819 writes
  code, the resolution algebra — scope ladder × relation lattice ×
  allow/deny (× field grants, D10) — gets a **normative truth table in the
  spec, asserted by a property test**. What does `deny item.update@team`
  do to a holder of `item.update@own` whose own item is also their team's?
  (Answer under the lattice: `@own ⊄ @team` in general — the table must
  say so explicitly.) This artifact is the difference between deny being
  a feature and deny being a support burden.
- **D9 (no anonymous reporting).** Right direction; two problems in the
  filed shape:
  - **RADD-828's text contradicts the recorded decision.** D9 keeps
    `/public/pages` + `/public/csat`; the issue's Done-when ("no endpoint
    outside /auth answers without a CurrentUser") strips them. The issue
    predates the decision. Rewrite before handoff.
  - **"The account holds nothing but the Baseline" is a hole as filed**:
    the same release deliberately does not narrow existing Baselines, so
    enabling email ingest hands every stranger full `item.read` +
    `page.read`. Fix: a dedicated seeded **Requester** role for
    `UserSource.EMAIL` accounts, decoupled from the Baseline (→ Q1).
- **D10 (relations × field grants).** Keep, but it doubles the resolver
  surface and it breaks a shipped contract nobody listed:
  `readonly_field_keys` is documented per-(actor, project) and
  item-INDEPENDENT (`fields/service.py:410-415`) — the seam behind spec
  96's "disable un-writable fields up front". `write Priority @assigned`
  and `item.update@own` make writability per-ROW. A new work item (§3
  step 10b of the plan) gives the SPA a per-item capability answer, or the
  wave reintroduces edit-then-error and violates the project's own
  convention.
- **D14 (can't grant what you don't hold).** Correct, needs one word:
  the intersection is **scope-aware** — "holds the atom *at the scope of
  the grant being made*". A project admin granting within their project
  passes on project-scoped holdings; lacking the atom globally is not a
  refusal. Without this, D3 delegation mostly refuses.

## Superseded / no action

- **D8** — superseded by D5 (as recorded).

## Cross-cutting: one syntax, not two

§5.2 writes `comment.delete.own`; §5.4a writes `item.update@own`. These are
the same concept in two notations, and an executor following §5.2 literally
mints dotted atoms that §5.4a's parser will not read. **Normative form:
`resource.action@relation`** (`attachment.delete@own`). §5.2's table is to
be read with `@own` substituted. RADD-816 and RADD-823 both carry this
note.

## Cross-cutting: hardcoded own-rights become grants

F4's root cause is that "author may delete own comment/worklog" is
hardcoded while the atoms mean "others'". Under relations the honest form
exists: seed the Baseline (or a builtin role) with `comment.delete@own`,
`worklog.delete@own`, `attachment.delete@own` and delete the hardcoded
author checks — every refusal becomes grant-explainable, which is D1's
stated principle (→ Q4). Under no-backcompat this is a clean break, not a
migration project.
