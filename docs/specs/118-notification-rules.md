# Spec 118 — Granular notifications: scoped subscriptions + a per-event channel matrix

## The problem

A notification preference was one answer per person per TYPE, for the whole instance:
`notification_prefs.muted_types` and `notification_prefs.email_types`, two JSONB lists
keyed only by `NotificationType`. Three things that people actually want were
inexpressible, and one of them was inexpressible *structurally*.

**You could not say where.** `consumer.recipient_ids` was watchers ∪ members of the
item's participant teams, and that was the entire ambient recipient set. "Tell me what is
arriving in the Platform project" had no representation at all — the only way to find out
was to go and look. Nor could you say "keep telling me about state changes on my own
issues, stop telling me about the ones I merely watch": the preference had no notion of
relation, so the mailer gave a watcher and an assignee the same answer about the same
type.

**You could not say email-only.** A muted type never became a notification row, and the
mailer mails rows — so "email me when something is assigned to me, do not clutter my
inbox" was not a preference the model could hold. That is not an omission, it is the
shape: the mute lived in the row's EXISTENCE.

**And some things reached nobody at all.** An edit that changed neither state nor
description was silent to everyone watching it — a reprioritised, relabelled,
re-estimated issue produced no notification of any kind. `page.created` notified nobody.
And every comment on a wiki page raised `KeyError` inside the consumer's per-event
SAVEPOINT, was logged, and was skipped (RADD-1056, below).

## The model

A person's notification behaviour is a set of **rules**, one row per (scope, target):

```
notification_rules(user_id, scope, scope_id, channels)
```

`channels` is a SPARSE map `{kind: off|inbox|email|both}`. Sparse is load-bearing — see
below.

Six scopes, in two families:

| Scope | `scope_id` | Means |
|---|---|---|
| `own` | NULL | You are the assignee or the reporter. |
| `participating` | NULL | You watch it, were shared into it, or were named in it. |
| `teams` | NULL | The item's Team field is one of YOUR teams. |
| `project` | a project | Everything in that project. |
| `space` | a wiki space | Everything in that space. |
| `team` | a team | Everything filed against that team. |

The first three are RELATIONSHIPS: they hold or they do not, and there is nothing to
point them at. The last three are SUBSCRIPTIONS: the row exists because someone named a
target.

`teams` and `team` are two scopes rather than one because they answer different
questions. "Issues filed against any team I belong to" is a standing relationship that
follows you as you join and leave teams; "this team" is a choice about a team you may not
even be in.

### Channels are independent

`Channel` is `off | inbox | email | both`, and `email` with no inbox row is a real state.
That is the fourth cell RADD-686 could not reach, and reaching it is what forced the
delivery change in RADD-1054.

### Resolution: most specific wins, with sparse fall-through

`notify/rules.py` is pure and unit-tested. Scopes are consulted in this order, skipping
any that does not apply:

```
own > participating > a subscription to the item's TEAM
    > my-teams > a subscription to its PROJECT > … to its SPACE
```

The first rule row that has an OPINION about this kind decides. A rule states only what
it has an opinion about, so subscribing to a project to hear about new issues does not
overwrite what you said about comments on your own work.

If nobody has an opinion, the **first applicable scope's default** answers — not the last,
and not a global default. That is what makes "I subscribed to a project" mean "and
everything about my own issues is unchanged".

**An unsubscribed project is not a scope with an empty opinion — it is not a scope at
all.** Otherwise its `off` default would sit above `participating` in the order and
swallow it, and watching an issue would stop working in every project nobody had
subscribed to.

### Personal kinds resolve through `own` alone

`assigned`, `mentioned`, `participant_added`, `approval` and `automation` are addressed
AT a person by the event itself. There is no relationship to resolve, because the event
picked the recipient; the settings page greys the other two columns.

Getting this wrong is not cosmetic. `approval` goes to eligible approvers, who are
frequently neither the assignee nor a watcher — resolving it through a relationship scope
would have handed them `off` and ended approvals in silence.

### The defaults reproduce RADD-686's CHANNELS exactly

`DEFAULT_MATRIX` is the acceptance bar of the whole spec, and
`tests/test_notify_rules.py` pins it kind by kind against `DEFAULT_EMAIL_TYPES` rather
than a copied list: **for anyone the old fan-out already reached, a user with zero rule
rows resolves to precisely what they resolved to before.** Every pre-existing kind is
inbox-on in `own` and `participating`, the personally-directed five are also mailed as
they happen, and everything else is left to the digest.

That is a claim about CHANNELS. The AUDIENCE deliberately widened — see below — and
stating the two as one sentence is how a parity promise stops being true without anyone
editing it.

`own` and `participating` are identical, and that is not laziness — RADD-686 had no notion
of relation, so any difference introduced here would be a behaviour change for someone who
never asked for one. The columns exist so they CAN be told apart from now on.

`teams` starts `off` outright. It is the one genuinely new reach among the COLUMNS, and
defaulting it on would subscribe every member of a team to their whole team's traffic on
deploy day.

### The `own` scope widens the audience, on purpose

Before this spec the ambient recipient set was watchers ∪ participant-team members, full
stop. An assignee or reporter who was not watching heard nothing ambient at all — the only
reason they usually did is that creating, being assigned or being named auto-watches, and
`item_watchers` is what carried them. `planner.Audience.own` now holds the assignee and
the reporter unconditionally, because "my own items" is the scope that was asked for and a
column claiming to name them has to contain them.

Two consequences, stated here because each reads as a bug when it is met undocumented:

- **Unwatch no longer silences an assignee.** It removes the PARTICIPATING relation only;
  `own` still applies. The control for it is the `own` column — set its cells `off` and
  they are silent again. Under the old model there was one answer per type for the whole
  instance, so Unwatch was the only lever there was; replacing that lever is the spec.
- **On an instance built by IMPORT this is genuinely new mail.** A bulk import emits
  `silent` events and the consumer skips them, so imported items carry no auto-watch rows:
  their assignees and reporters were reachable by nothing ambient before. `commented`
  defaults to `both` in `own`, so on the first comment after upgrading they get the mail an
  assignee on a natively-created item has always got. Nothing is retroactive — only events
  from here on — but the volume change on a Jira-imported instance is real and is worth
  knowing about before it arrives.

`test_notify_scoped_fanout.py` pins all three facts (an assignee who never watched hears
about a comment; turning the `own` cells off silences them; unwatch plus `own` off is
silence) so the widening cannot be walked back, or widened further, by accident.

### The kind vocabulary

`notify/kinds.py` holds one ordered constant — wire value, label, description, personal —
and the preferences endpoint serves it. The panel this replaces held its own
`Record<NotificationType, string>` in TypeScript, so a kind added on the server had no row
in the UI and nothing failed: it simply could not be configured.

Three kinds are new, and all three are `off` in every relationship scope, so an instance
that never opens the settings page cannot notice they exist:

- **`created`** — an issue was filed. Reached only its assignee before.
- **`updated`** — a field moved that no semantic type covers, carrying the field names. A
  digest line reading "Ada updated the issue" among eleven others carries no information.
- **`page_created`** — a page was created in a space. Notified nobody before.

## Fan-out

`planner.Audience` splits the ambient recipient set four ways — `own`, `participating`,
`in_my_teams`, `subscribers` — and the planner stamps each recipient's RELATION on the
`PlannedNotification`. That is where it has to happen: the fan-out that built the sets is
the only place that still knows which one someone came out of, and recovering it
afterwards would mean re-deriving what was just decided. The planner stays pure;
`Audience` is its input.

Three queries beyond the old flat version: the subscriber lookup (one indexed read over
`ix_notification_rules_target` per event, matching project and team at once), the my-teams
narrowing, and the team-member expansion behind it. The my-teams path narrows from the
RULES side first — a `teams` row carries no `scope_id`, so it cannot be looked up by
target, and resolving every team of every candidate recipient is a query per person for
an answer almost always empty.

`_apply` resolves the CHANNEL before calling `_allowed`. Same rows either way, but
`_allowed` costs a permission resolution plus a relation row check per recipient, and this
spec multiplied the recipient set by everyone subscribed to the project; an `off` verdict
should cost a dictionary lookup.

### What the consumer loop costs, and where it stops being flat

Worth stating because none of it shows up until somebody uses the feature, and then it
shows up as consumer lag rather than as anything about notifications:

- **Per surviving recipient, per event: roughly one permission resolution.** `_allowed`
  resolves `permissions_for_projects` and, for a relation-scoped reader, an async row
  check; the page path pays `page_access` per recipient instead. The channel filter runs
  first, so this is per SURVIVOR and not per candidate — which is what keeps a project with
  four hundred subscribers who all left `commented` at `off` costing four hundred dict
  lookups. It is also why the cheap thing to widen is the audience and the expensive thing
  is anyone whose rules say yes.
- **`readable_page_ids_for_users` is linear in users**, one `page_access` walk each — a
  space role plus every restriction on the ancestor path. Batched per PAGE (one edit, one
  call), so a busy wiki costs watchers + space subscribers per edit and nothing else.
- **`my_teams_members` expands the item's team per item event, once any `teams` rule
  exists anywhere on the instance.** `team_scope_user_ids` is a single indexed read that
  answers empty on an instance where nobody uses the column, and the expansion behind it
  never runs; the first person to switch that column on turns it into a `list_team_members`
  per item event that carries a team.
- **The subscriber lookup is one indexed read per event** regardless of how many people
  subscribe, because a row's channels are deliberately not consulted in SQL.

Nothing here is paginated or budgeted, and it does not need to be at this size — the
bounded thing to watch is a very large team plus a widely-used my-teams column, which is
where a per-event member expansion would want a cache.

## The wiki joins the outbox

RADD-719 delivered page notifications synchronously from inside the save request, arguing
that page edits are rare and "a consumer would mean a second delivery path to keep correct
for a volume that does not need one". The volume was never the argument that mattered — it
WAS the second delivery path, and it drifted exactly where a second path drifts:

- it knew about page watchers and could not be given a space subscription without growing
  a second copy of the resolver;
- it wrote notification rows with **no read gate**, so an edit told whoever had once
  clicked Watch, whatever the space had decided about them since;
- and `page.created` was never wired to it at all.

`notify/pageevents.py` is the wiki's half of the consumer, on the same three seams. The
gate is `pages.refs.readable_page_ids_for_users` — a page's visibility is a space role
PLUS every restriction on the ancestor path (RADD-948), which is the wiki's answer to give
and not notify's to reimplement. `pages/watchers.py` keeps the table and its accessors and
loses `notify_watchers`; `pages.update_page` still auto-watches the editor on the write
path, which is why the watch-only bootstrap has nothing to contribute for page events.

Page events gained `page` and `page_space` SUBJECTS (RADD-923), so the payload carries the
slugs a notification links with and the space id a subscription matches on — without
notify importing `pages`, which it may not (load order) and whose models it may not reach
(the spine rule). Declaring the subjects on the `EventTypeSpec` means the loader refuses to
boot if either ref goes missing.

What the loader checks is that the ref EXISTS, not that it resolved — and a subject is
resolved by reading the row. `hard_delete_page` deleted, flushed, and emitted afterwards,
so `page.deleted` carried `"page": null` on the one event about a page nobody can look up
afterwards. It emits first now; inside one transaction the order is invisible, because the
outbox row and the deletion commit together or not at all
(`tests/test_event_subjects.py`).

### RADD-1056: page comments notified nobody, ever

`comments` has been polymorphic since RADD-717 — a comment's parent is an item OR a page,
and the event says which in `entity_type`. `consumer._handle_comment_created` did not
look. It read `payload["item"]["id"]` unconditionally, and a page comment's `item` subject
is NULL by construction (the emitter resolves it only for item parents). So every wiki
comment raised `KeyError` inside the per-event SAVEPOINT, was logged, and was skipped:
**page comments produced zero notifications for the entire life of the feature**,
including a comment that @-named someone directly.

It survived because `page_updated` worked. The wiki's notifications looked alive.

## Delivery

`notifications.inbox` and `notifications.email`, stamped at the write from the verdict.

RADD-686 filtered each mail candidate in Python against its recipient's `email_types`, and
argued the predicate could not be SQL because it was per-user. It could not — *while the
only thing a row remembered was its TYPE*. That is also why the mailer could never honour a
scoped preference: by the time it saw a row it had no idea whether the person got it
because they were assigned the issue or because they had subscribed to the project. The
decision now happens once, in the code that still knows the relation, and both email loops
read a column. `mailer._wanted` is gone; `_pending` gains `email IS TRUE`.

`off` writes no row at all — the mute moved out of the row's existence and onto its
columns. Inbox reads filter `inbox IS TRUE`; the digest does too, so an email-only row
cannot be batched into a digest by the tick that races the mailer.

**The trap the two-boolean model opens.** `mailer._pending` skips READ rows, and an
email-only row can never be opened because it is not in the list — so "mark all read"
would have silently cancelled a send the person explicitly asked for. Both mark-read paths
are scoped to inbox rows.

### Known issue: an email-only row has no second chance

An email-only row is the immediate mailer's alone, and the immediate mailer only looks at
rows younger than `notify_email_max_age_hours` (24h). So if there is nowhere to send FROM
for longer than that — `can_send` false, i.e. no sender row and no `RADD_SMTP_*` — the row
is never sent, never stamped, and never picked up by anything else. It is not in the inbox
either, because that is what email-only means. It is simply gone, silently.

This is **not** the retry ladder's case. `retry.py` covers a send that was ATTEMPTED and
failed: 1m/5m/30m, then a terminal stamp, all inside the age window. This is the case where
no attempt is ever made, which the ladder never sees, and it is created by the same choice
that fixes the double-send: the digest is a digest of the inbox (`inbox IS TRUE`), so it
cannot be the safety net for a row that was never in one.

Bounded, and left as it is for now: it needs an instance with an email-only cell saved AND
a relay down for a day, and the alternative — letting the digest sweep email-only rows —
reintroduces the double-send on every tick where the two loops race, which is a bug that
fires in normal operation rather than in an outage. The honest fix is a terminal state on
the row that says "aged out, never attempted" and a place to see it; the monitoring page
(spec 105) is where that belongs, and it is not built.

## Settings UI

`/settings/notifications` — its own tab under Account, not a Profile section: it is a
13 × 3 grid plus a subscription list, and a preference nobody can find is a preference
nobody changes.

The cell control is a menu with five choices (Inherit, Off, Inbox only, Email only, Inbox
and email) behind a trigger showing two channel marks. **Two checkboxes were rejected**:
they can say off / inbox / email / both but they cannot say UNSET, and unset is most of
this grid. Every untouched cell resolves to something, from somewhere, and a control that
renders inheritance as "unchecked" lies about the two cases a preference exists to
distinguish — "I turned this off" and "I never said". The trigger shows what the cell
RESOLVES to, dimmed when inherited, naming the source on hover.

A subscription's unset cell falls back to the person's own column rather than to a
default, because that is what the resolver does; showing `off` there would tell them their
own preferences had stopped applying. Only ambient kinds get a cell — a personal kind
resolves through `own` alone whatever scope you are looking at, so offering the control
would be offering one that cannot do anything (the spec-96 failure, in a preference rather
than a field).

## Migrations

**`d118notifrules`** creates the table and carries every stored preference into `own` and
`participating` ONLY. Muted → `off`, emailed → `both`, everything else → `inbox`; the kind
list is a frozen snapshot, `d686emailtypes`' rule. Writing the same preference into
`teams` as well — as first sketched — would have subscribed every existing user to their
whole team's traffic on the strength of a checkbox they ticked about their own issues.
Then it drops `muted_types` and `email_types`.

Two PARTIAL unique indexes rather than one constraint: relationship rows carry
`scope_id IS NULL`, and Postgres counts NULLs as distinct, so a plain
`UNIQUE (user_id, scope, scope_id)` would let a person hold two `own` rules and leave the
resolver answering with whichever it indexed last.

**`d118notifchan`** adds the two channel columns, backfilled `inbox = true,
email = false`. The inbox half is exact (a muted type never became a row); the email half
cannot be recovered, because the relation that would decide it was never recorded. The
cost is bounded — a row is only eligible for the immediate mailer while unread, unemailed
and under `notify_email_max_age_hours` — so at most one day's un-actioned notifications
arrive in the digest instead of individually. Nothing is lost. Guessing from a frozen
default set would have mailed people about types they had turned off, which is the worse
error.

## Where it lives

| | |
|---|---|
| Vocabulary | `notify/kinds.py` |
| Resolver (pure) | `notify/rules.py` |
| Storage + seams | `notify/models.py`, `notify/service.py` |
| Preferences payload | `notify/prefs.py`, `notify/schemas.py`, `notify/router.py` |
| Fan-out | `notify/planner.py` (`Audience`), `notify/consumer.py` |
| Wiki fan-out | `notify/pageevents.py`, `pages/refs.py` |
| Delivery | `notify/mailer.py`, `notify/emailer.py` |
| UI | `web/src/routes/settings/notifications.tsx`, `web/src/components/settings/notifications/` |
| Proof | `web/scripts/notification-matrix-proof.mjs` (30 checks, both themes) |
| Tests | `test_notify_rules.py`, `test_notify_scoped_fanout.py`, `test_notify.py`, `test_notify_mailer.py` |

## Deliberately not built

- **Per-project admin notification schemes** (the Jira model). This wave is per-user only.
- **New channels.** No Slack, no webhook delivery — `Channel` is inbox and email.
- **A digest with scope.** `email_digest` stays one boolean: it is about the SHAPE of the
  mail, not about which events reach you, and it is the one preference with no scope to it.
