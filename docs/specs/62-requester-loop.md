# Spec 62 — Requester feedback loop: contacts, outbound mail, public forms

Service-desk wave, part 2. Spec 30/47 made intake work (reporter field, IMAP
poll, reply threading) but the loop is one-way: a requester who files a ticket
never hears back. This spec closes it: reporters auto-watch, external senders
become addressable contacts, agents' public comments go back out by email, and
forms get a public (tokened, no-login) submit path that feeds the same loop.

## 1. Shared SMTP helper (`radd/smtp.py`)

- `send_message(to_address, subject, body, *, to_name="", headers=None) -> None`
  — sync stdlib smtplib (callers wrap in `asyncio.to_thread`), config from the
  existing `smtp_*` settings, no-op guard stays at the callers (`smtp_host`
  empty = disabled). `notify/emailer.py` refactors onto it; mailintake (this
  spec), csat (spec 65), and the automation send_email action (spec 66) reuse it.

## 2. Reporter auto-watch (notify module)

- `planner.plan_item_created` adds the payload's `reporter.id` to the watch
  set; `plan_item_updated` watches the NEW reporter when a change diff touches
  `reporter`. Pure planner + tests — notifications/digests then flow to
  reporters through the existing machinery, nothing else changes.

## 3. Mail contacts (`mail_contacts`, mailintake module)

- Table: `item_id` (PK, FK work_items CASCADE), `email`, `name` (default ""),
  `last_message_id` (nullable — most recent inbound RFC Message-ID, for
  threading headers), created/updated timestamps. One external requester per
  item (v1).
- Intake creates a row whenever the sender resolves to NO active user;
  `parsing` additionally captures the inbound `Message-ID` and updates
  `last_message_id` on threaded replies. Registered senders get no row (they
  are reporters and now auto-watch).
- Seam: `mailintake.service.contact_for_item(s)` + `upsert_contact` (public
  functions; spec 65/66 consume them).
- `GET /items/{item_id}/mail-contact` (item.read; 404-quiet) → `{email, name}`
  — the issue rail shows an "External requester" chip from it.

## 4. Auto-ack + outbound replies (mailintake)

- **Ack:** when intake CREATES an item and captured a contact, send an
  acknowledgment email — subject `[KEY] title` (the key is what makes the
  requester's replies thread), body template in types.py with the item key.
  Config `mail_send_ack: bool = True`; silently skipped without SMTP. Public
  form submits (§6) with an email also get the ack.
- **Replies out:** new outbox consumer `mailintake/outbound.py`
  (CONSUMER_NAME `mailintake.outbound`, registered next to the poller's
  runner): `comment.created` events where the item has a contact, the comment
  is PUBLIC, and the actor is NOT the SYSTEM actor → email the contact the
  comment body (plain text) with `Re: [KEY] title`, `In-Reply-To`/`References`
  from `last_message_id`. The SYSTEM gate keeps inbound-mail comments and
  automation comments from echoing back. Send-decision is a pure function
  (`should_reply(...)`, tested).

## 5. Plus-address project routing (mailintake)

- `parsing` inspects `To`/`Cc`/`Delivered-To`/`X-Original-To` for a plus tag:
  `support+td@…` routes intake to project key `TD` (case-insensitive; unknown
  key → fall back to `RADD_MAIL_PROJECT_KEY`). `EmailPlan` gains
  `project_key: str | None`; tested in the parsing unit tests.

## 6. Public forms (forms module)

- Form model: `allow_public` (bool, default false) + `public_token`
  (String(64), unique, nullable) — generated (`secrets.token_urlsafe(32)`) the
  first time public is enabled; disabling keeps the token (re-enable = same
  link). Builder validation unchanged.
- Unauthenticated router: `GET /public/forms/{token}` → render payload (name,
  description, title_prompt, fields with labels/required + the field-definition
  bits the widgets need); `POST /public/forms/{token}` body
  `{title, values, email, name?}` — 404 unknown token, 409 disabled. Submit
  runs as the SYSTEM actor through the existing `submit_form` path; `email`
  resolving to an active user → that user becomes reporter; otherwise reporter
  stays NULL and a `mail_contacts` row is upserted (name/email) → the
  requester is addressable (ack + comment replies + CSAT later).
- No rate limiting / captcha in v1 (self-hosted, LAN-first — noted).

## Frontend

- Public SPA route `/public/forms/$token` OUTSIDE the auth guard (root-level
  like /login): reuses the form-submit rendering + email/name inputs, success
  screen shows the created issue key.
- Form builder: "Public link" toggle + copy-URL row (`{app_base_url}/public/forms/{token}`).
- Issue rail: External-requester chip (email, tooltip name) when a contact
  exists.

## Tests

Planner reporter-watch (create + reporter change); `should_reply` matrix
(no contact / internal comment / SYSTEM actor / happy path); plus-address
parsing; public submit integration (contact row, reporter resolution, disabled
409, bad token 404).

## Known simplifications

- One contact per item; a second distinct sender on the same thread just
  updates `last_message_id`, not the address.
- Outbound covers COMMENTS only (state changes don't email the contact; the
  resolution notice arrives with CSAT in spec 65).
- No HTML mail — plain text everywhere, matching the digest emailer.
- Public submit trusts the given email (no verification loop).

## As-built notes

- **Explicit-NULL reporter**: `items.create_item` now resolves `reporter_id` by
  the `model_fields_set` idiom (omitted = acting user, explicit null = NULL) so
  intake/public submits can leave the reporter unset. The Jira importer omits
  the key for unmatched reporter emails to keep its "unknown ⇒ the importing
  user" behavior; `forms.submit_form` grew a keyword-only `reporter_id`
  override (sentinel default = pre-62 behavior).
- **Outbound cursor seeds at the stream HEAD** on first start (googlechat
  idiom, not webhooks' from-0 replay) and is committed BEFORE sending —
  at-most-once: for email a dropped reply beats a duplicate. Delivery failures
  log + advance (no retry queue). The loop runs whenever `run_workers` is on,
  even without IMAP config (public-form contacts need it); SMTP unset =
  cursor advances silently, so enabling SMTP later replays nothing.
- **Acks also thread**: when intake holds the inbound Message-ID, the ack
  carries In-Reply-To/References (superset of the spec's subject-only
  threading). Public-form acks have no message id → subject threading only.
  Acks send post-commit from the poller; the public-form ack sends in-request
  (pre-commit — accepted, a stray ack beats extra machinery).
- **Reply-path contact capture**: a threaded reply whose item has NO contact
  yet and whose sender matches no active user creates the contact (covers a
  registered user filing + an outsider replying on the thread); an existing
  contact's address is never overwritten, only `last_message_id` (+ a blank
  name is backfilled).
- **forms → mailintake is a deferred, feature-detected edge** (mailintake
  loads after forms in RADD_MODULES): with the module disabled, public submits
  still work — the requester just isn't addressable.
- The mailintake dispatcher now gates on `run_workers` (spec 48 worker split —
  docs already claimed it; the code didn't).
- Extra config beyond the spec: `RADD_MAIL_OUTBOUND_POLL_SECONDS` (default 5s).
- `allow_public` is PATCH-only (not on FormCreate) — the builder shows the
  toggle once the form is persisted, mirroring the test-panel pattern.
