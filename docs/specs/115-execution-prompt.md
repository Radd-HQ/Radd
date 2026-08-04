# Spec 115 — execution brief

**Read this first, then `115-access-control-audit.md` in full, then the issues.**

You are executing the access-control wave: **RADD-813** (14 children) and
**RADD-827** (Groups as a first-class entity). Every decision has been made and
recorded — §0 of the audit carries D1–D14 with their reasoning. You are not
being asked to re-litigate the design. You are being asked to build all of it.

---

## The one rule that overrides your instincts

**Everything ships in ONE release. Nothing is deferred, stubbed, or "left as a
follow-up".**

An agent working a list this long will feel pressure to stop early — to land the
cheap items, file the rest as follow-ups, and report success. That is the failure
mode this brief exists to prevent. The wave is coherent: the scope model, the
verb model, relations, deny and the inspector each assume the others. Shipping
half leaves the system in a state that is *worse* than either end — two
vocabularies live at once, which is exactly the drift the audit was written to
remove.

Concretely:

- **Do not** narrow scope and call it done. If an issue says the relation must
  reach reports, search, MCP and dashboard counts, all four are in scope.
- **Do not** file "part 2" issues for work already specified. If you discover
  *genuinely new* work, file it — that is correct — but the original issue does
  not close until its own Done-when is met.
- **Do not** stop at "the tests pass". Several of these change what people can
  see; the bar is a browser proof against a real restricted account.
- **Do** report honestly if something is blocked. Blocked-and-said-so is fine.
  Silently narrowed is not.

If you run out of context, hand off with a written state note naming exactly
which Done-when conditions are met and which are not. Do not compress by
dropping work.

---

## Order of execution

Dependencies are real; this order respects them.

| # | Issue | Why here |
|---|---|---|
| 1 | **RADD-809** — inspector: resource grants, Team view, backlinks | Changes no behaviour. Build it first so every later step is *observable* — you can see what a model change did instead of inferring it from a 403 that did or did not fire. |
| 2 | **RADD-824** — `view.manage` client gates (the bug half only) | Live bug, independent, five minutes. Do not do the model half yet. |
| 3 | **RADD-814** — scope becomes a property of the grant | The root cause. Behaviour-identical migration; collapses `require_anywhere`/`readable_projects` and the three client seams. |
| 4 | **RADD-810** — the ten mismatched client gates | Obsoleted *by* 814 — resolve them in its terms, do not fix them first. |
| 5 | **RADD-823** — relations mechanism (kernel) | Depends on 814's vocabulary. |
| 6 | **RADD-817** — items adopt relations | First adopter. |
| 7 | **RADD-816** + rest of **RADD-824** — verb normalisation, `manage` demotion | Breaking renames; needs the inspector (1) to verify and 823 to have settled `@own` syntax. |
| 8 | **RADD-819** — deny precedence | Additive, inert until used. |
| 9 | **RADD-822** — field scope vs field grants wording | Independent; do it whenever. |
| 10 | **RADD-818** — plugin access resources + uninstall sweep | Needs 814 and 816 vocabulary settled. |
| 11 | **RADD-826** — project admins assign roles | Needs D14's intersection. |
| 12 | **RADD-815** — matrix by resource, presets + sentence builder | The UI for everything above; do it once the model is final. |
| 13 | **RADD-828** — strip anonymous reporting, email provisions accounts | Independent of the model work; keep `/public/pages` and `/public/csat`. |
| 14 | **RADD-825** — Baseline pre-flight report | Ships the *capability*; see below. |
| 15 | **RADD-820** — grant expiry + granted-by | Smallest, independent. |

**RADD-827 (Groups)** is a separate epic and needs its own spec written before
building. It is not part of this release unless explicitly asked — but
RADD-823's `@team` must resolve through a **single function** so the group graph
can be swapped in later without touching call sites.

---

## The one thing that must NOT ship flipped

**Do not change the Baseline row's value on an existing instance.**

The Baseline is an editable DB row (RADD-773), and on an instance that has never
written a grant it is the *only* thing granting anyone read access. Flipping it
to `item.read@own` in a migration removes read from every account at once —
which looks exactly like the bug this whole wave exists to remove.

What ships: `item.read@own` expressible and enforced, the pre-flight report, and
a **fresh-instance seed** of `item.read@own`. What does not ship: a migration
that rewrites an existing row. An admin flips it in Settings once their
pre-flight report is clean. Same for `page.read`.

This is not "holding work back" — the capability is complete. It is refusing to
make a policy decision on the operator's behalf.

---

## Definition of done, per issue

An issue is done when **its own "Done when" paragraph is literally true**, not
when the code looks right. Before moving on:

1. Its Done-when conditions are individually verified, not assumed.
2. `cd server && uv run pytest -q` is green — the whole suite, not a subset.
3. `cd web && ./node_modules/.bin/tsc -b` is silent.
4. One commit, `[RADD-####] description`, naming that issue only. Reference
   other keys in the BODY, never the subject — the release procedure extracts
   keys from subjects and assumes exactly one.
5. A comment on the issue saying what shipped, what it cost, and **what
   surprised you**. The last part is the part nobody can reconstruct later.
6. `transition_item` → `Waiting for release`.

---

## The verification bar

`CLAUDE.md` has the full list. These apply directly to this wave:

- **Building is not verifying.** Every issue that changes what someone can see
  needs a browser proof against a **real restricted account** —
  `web/scripts/restricted-access-proof.mjs` and `space-access-proof.mjs` are the
  patterns; `scoped-member-proof.mjs` too.
- **A test that passes vacuously is worse than one that fails.** Prove each new
  assertion FAILS on the pre-change code before you trust it passing. Revert,
  rebuild the bundle, re-run, restore. RADD-808's proof passed on the broken
  build for a year because it asserted the wrong surface.
- **Verify against a real actor.** An admin passes every check; a permission
  test run as an admin proves nothing. The dev DB has
  `proof-member@example.test` and `clean-member@example.test`.
- **Wire constants have no compiler.** Any enum value crossing to the SPA gets a
  contract test — `server/tests/test_permission_scope_contract.py` is the
  pattern, and RADD-818 extends it to plugin-declared scopes.
- **Route order matters.** A literal declared after `/x/{id}` is unreachable;
  `tests/test_route_shadowing.py` covers the app, keep it passing.

---

## Traps specific to this wave

These are the ones that will cost a day each if rediscovered:

1. **Child content must inherit the parent's relation.** If `item.read@team`
   hides an issue, its comments, attachments, worklogs and history must vanish
   with it. Separate tables, separate endpoints; each one that forgets leaks
   exactly the data the restriction protects. Put it on the shared item
   resolution seam — never re-check per child table.
2. **Every counting surface inherits the filter, or none do.** A restricted user
   seeing "42 issues" on a dashboard and 3 in the list is the classic failure.
   Reports, board column counts, swimlane rollups, search, SLQ, MCP
   `find_items`.
3. **A relation declares two forms and they must agree.** `where(actor)` for
   filtering, `holds(actor, row)` for gating. Neither is derivable from the
   other. A contract test must assert they agree on a fixture — a relation whose
   filter and predicate disagree is a silent leak.
4. **`has_manage` is being removed as a bypass (D1).** Expect flows that
   silently passed to start refusing. That is the point; call each one out in
   the issue comment rather than restoring the bypass to make a test green.
5. **Atom renames must rewrite stored data (D4).** Roles hold atom *strings*; a
   stale one 500s `GET /roles` because `RoleRead.permissions` is typed. Migrate
   role JSONB, `api_tokens.scopes` and `access_grants`, each guarded on the
   table existing, and emit an event per change. RADD-701 is the precedent.
6. **Group nesting is a recursive CTE on the hottest path.** Memoise per request
   beside `baseline_permissions` and `readable_projects`. (Relevant only if
   RADD-827 is in scope.)

---

## Tracking

`CLAUDE.md` §"Tracking work on the live instance" governs, and the local `track`
skill has the mechanics. Work through the **MCP tools**, not REST; every REST
fallback is an MCP gap worth naming.

Attribution is the owner. One commit per issue. Log the session's time derived
from timestamps, never estimated, and never more than the session lasted.

---

## Releasing

When **every** issue in the order above sits in `Waiting for release`:

1. Pre-flight per the `release` skill. Note that the date-stamp check currently
   matches `CLAUDE.md` and has done for several releases (RADD-811) — that is
   pre-existing, not yours.
2. `git tag -a vX.Y.0` — this is a **minor**, not a patch: the release notes are
   full of "now you can".
3. Bump `image.tag` in the deployment repo once CI publishes.
4. Verify the running image and the live bundle, not just the CD status.
5. The Forgejo release webhook sweeps the issues to Done automatically. Confirm
   it did; sweep by hand if not.

**Release notes must say plainly:**

- `has_manage` no longer bypasses field and relation checks — some
  project-manager actions now refuse where they silently passed.
- Atom renames were applied automatically to roles, tokens and grants; the
  events name every role that changed.
- The Baseline was **not** changed on existing instances. Leaving `page.read` in
  it exposes pages to email-provisioned requester accounts; run the pre-flight
  report before narrowing.
