# Spec 71 — Approvals on workflow transitions

Target-features wave, part 4. JSM-style approvals built INTO the spec-61
transition machinery rather than beside it: "require approval" is just another
transition RULE, configured in the same editor on the project Workflow settings
page, evaluated by the same guard path. A new small `approvals` module owns the
request/vote lifecycle; the workflow guard consumes it through a deferred seam
(exactly how `require_estimate` reaches timelogging today).

## 1. Rule kind (workflow module)

- `TransitionCheck.REQUIRE_APPROVAL` with params
  `{user_ids: [...], team_ids: [...], required: N>=1}` — approver users and/or
  teams (members resolved LIVE at vote time), N-of-M required approvals.
  Write-validation on the transitions CRUD: subjects exist in the project's
  workspace (409), `required >= 1`, at least one subject (409); rules stay
  JSONB `{check, params}` so no schema change on `workflow_transitions`.
- Guard evaluation: `ItemSnapshot` gains `approved_to_state_ids: set[str]` —
  the to-states for which THIS item currently holds a CONSUMABLE approved
  request. `require_approval` passes iff the target state is in the set;
  failure string: `approval required (2 of 3 approvers)`.
- `check_transition` builds the snapshot via a deferred, feature-detected
  import of `approvals.service.approved_target_state_ids(session, item_id)`
  (module absent → empty set → the rule always fails with a clear string; the
  transitions editor hides the option when the module is off).
- On a SUCCESSFUL transition into an approved target, items→workflow calls
  `approvals.consume(session, item_id, to_state_id)` (same deferred seam) —
  the approved request flips to `applied` so one approval unlocks ONE move.

## 2. `approvals` module (new)

- `approval_requests`: id, item_id FK CASCADE ix, transition_id FK
  `workflow_transitions` SET NULL (rule may be edited/deleted later; params
  are SNAPSHOTTED onto the request: `approver_user_ids`, `approver_team_ids`,
  `required`), `to_state_id` FK states, requested_by FK users, note,
  `status` StrEnum `pending|approved|declined|canceled|applied`, timestamps.
  ONE live (`pending|approved`) request per (item, to_state) — app-level 409.
- `approval_votes`: request_id FK CASCADE, user_id, `verdict` `approve|
  decline`, note, created_at; unique (request_id, user_id) — revote replaces.
- Lifecycle: request created → approvers notified → votes accumulate.
  Eligibility at vote time = listed users ∪ CURRENT members of listed teams.
  `approve` count reaching `required` → status `approved` (+ auto-apply, §4).
  ANY `decline` → status `declined` (requester notified; a new request can be
  raised after addressing feedback). Requester or `project.manage` can cancel.

## 3. API

- `GET /items/{id}/approvals` (item.read) → live request + vote state +
  history list.
- `POST /items/{id}/approvals {to_state_id, note?}` (item.update) — 409 if no
  transition rule with `require_approval` matches (current state → to_state,
  wildcard included) or a live request already exists. Response embeds the
  resolved approver users (for the UI's avatars).
- `POST /approvals/{id}/vote {verdict, note?}` — eligible approvers only
  (403); revote allowed while pending.
- `DELETE /approvals/{id}` — requester or project.manage → `canceled`.
- `GET /approvals/pending` — MY queue: requests where I'm an eligible approver
  and status pending (powers the My Work card).

## 4. Auto-apply

- When the deciding vote lands, the approvals service applies the transition
  itself: `items.update_item(state_id=to_state)` acting AS THE FINAL APPROVER
  (real actor for audit). Other guards on that transition re-run — if one
  fails (e.g. estimate missing), the request STAYS `approved` (unlock banked)
  and the voter gets the 422 errors surfaced; anyone can complete the move
  later. Guard order puts `require_approval` last so failure strings compose.

## 5. Events + notify + automations

- `approval.requested` / `approval.voted` / `approval.approved` /
  `approval.declined` / `approval.canceled` (entity **item** → History feed
  picks them up via RELATED_EVENT_TYPES; payload: to_state name, requester,
  voter, verdict, counts).
- notify planner: `approval.requested` → notification to each eligible
  approver (`NotificationType.APPROVAL`, muteable); decision events → the
  requester. Approvers are NOT auto-watched (their involvement ends with the
  vote).
- automations catalog: the approval events join the Service-desk trigger
  group (item-scoped).

## 6. Frontend

- **Transitions editor** (`TransitionsSection.tsx`): a "Require approval"
  checkbox alongside the spec-61 checks; expands an inline config: approver
  user multi-picker + team multi-picker + "approvals required" number. Same
  immediate-PATCH idiom as the other rule edits.
- **Issue view**: an Approvals card in the properties rail (always-on
  conditional, like the requester chip): shows the live request (target
  state, votes x/N, approver avatars w/ ✓/✗) with Approve/Decline buttons for
  eligible approvers, cancel for the requester. When the CURRENT user's state
  picker targets an approval-gated state without an unlock, the picker's
  blocked tooltip (existing allowed-transitions plumbing) says so, and the
  rail card offers "Request approval →".
- **My Work**: an "Awaiting my approval" card listing `/approvals/pending`.

## 7. Tests

- guard: gated transition fails without request, passes with approved one,
  consumed after use (second move blocked again).
- N-of-M: 2-of-3 approves → approved + auto-applied; decline → declined;
  team-member eligibility resolved live; non-approver vote → 403.
- rule write-validation: unknown user/team 409, required<1 409.

## Known simplifications

- One live request per (item, to_state); per-SOURCE-state granularity is
  approximated by matching rules at request time.
- Approver set snapshots at request time except team MEMBERSHIP (live) —
  team edits mid-flight change the electorate, user-list edits don't.
- No delegation/vacation rules; decline is terminal for that request.

## As-built notes

- Migration `ea8e44297500` (`approval_requests` + `approval_votes`); module
  `radd.modules.approvals` appended LAST in `RADD_MODULES` (deps: events,
  workspace, auth, teams, workflow, items).
- `guards.evaluate` gained a third parameter `to_state_id: str | None` (the
  snapshot is built once per item, so the target rides the call, not the
  snapshot); `require_approval` failures are collected separately and appended
  LAST regardless of rule order — "Guard order puts require_approval last" is
  enforced in evaluation, not in stored rule order. Failure string:
  `approval required (N of M approvers)` where M = subject count (a team
  counts as one subject).
- Workflow's `_match` was made public as `transitions.match_row` so approvals
  matches rules exactly like enforcement does (exact beats wildcard).
- Approver-user write-validation = exists + active + workspace member OR
  instance admin (admins hold no membership rows).
- `GET /items/{id}/approvals` returns `live` as a LIST (one live request per
  (item, to_state), but several targets may be gated at once) and is
  empty-quiet (always 200) rather than 404-quiet; it also returns
  `requestable_to_states` computed server-side, so the client never
  string-matches failure text. Requesting is NOT gated on the enforcement
  mode — a rule's existence is enough.
- Auto-apply runs `items.update_item` inside a SAVEPOINT as the final
  approver; both `TransitionError` (other guards) AND `ForbiddenError` (the
  approver may lack item.update) bank the unlock — the request stays
  `approved` and the errors ride the `VoteResult.errors` for the UI toast.
  Consume-on-use lives in `items.update_item` AFTER the flush (deferred
  try/ImportError soft dep), so ANY successful move into the approved target —
  manual, bulk, automation — spends the unlock.
- Votes on a settled (non-pending) request 409; approve counts only verdicts
  from CURRENTLY-eligible voters (a vote survives, but stops counting, when
  the voter's team membership is revoked).
- `approval.requested` events additionally carry `eligible_user_ids` — the
  notify consumer (which loads BEFORE approvals, wire-string idiom like the
  SLA events) fans out to them without importing this module. Approval events
  are entity_type=item, so items/history.py needed no RELATED_EVENT_TYPES
  entry (csat precedent — noted inline there); `to_state`/`verdict` joined
  the history `_DETAIL_KEYS`.
- `GET /approvals/pending` filters by live eligibility only (approvers are
  explicitly named — no additional item.read filter on the key/title rows);
  notification delivery, by contrast, keeps notify's item.read recipient gate.
- Tests: `server/tests/test_approvals.py` (7) — guard+consume lifecycle,
  2-of-3 auto-apply with final-approver actor attribution, decline terminal,
  live team eligibility, write-validation 409s, banked unlock, cancel+queue.
