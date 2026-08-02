# Spec 65 — CSAT surveys

Service-desk wave, part 5. When a service-desk item resolves, the requester
gets a one-click satisfaction survey by email; ratings surface on the item and
in the spec-63 service-desk report. Opt-in per project — dev projects never
send surveys.

## 1. Module `csat`

- Table `csat_surveys`: id, `item_id` (FK CASCADE, unique — one survey per
  item ever), `token` (String(64), unique, `secrets.token_urlsafe(32)`),
  `rating` (nullable smallint 1–5), `comment` (Text, default ""), `sent_at`,
  `responded_at` (nullable), timestamps.
- New `SettingKey.CSAT_ENABLED` (BOOL, scopes instance/workspace/project,
  config default `csat_enabled = False`) — resolved per item project by the
  sender. Per-project opt-in is the whole point.
- **Sender**: outbox consumer (CONSUMER_NAME `csat.sender`) on `item.updated`
  events whose change diff moves state into a done-category state (resolve
  category via the payload's state embed / workflow seam). Guards: setting
  enabled for the project, SMTP configured, no existing survey row, and a
  recipient resolves — the item's mail contact (spec 62 seam) else the
  reporter's email (active user). Sends a plain-text email: thanks + five
  rating links `{app_base_url}/public/csat/{token}?rating=N`. Reopen→re-resolve
  does NOT resend (the unique row is the guard).
- Events `csat.requested` / `csat.responded` (+ automations-catalog rows).

## 2. Public API + page

- `GET /public/csat/{token}` → `{item_key, item_title, rating, responded_at}`
  (404 unknown). `POST /public/csat/{token}` body `{rating: 1..5, comment?}`
  → records; re-submits allowed (latest wins), `responded_at` stamped on
  first. Emits `csat.responded`.
- Public SPA route `/public/csat/$token` (outside the auth guard, spec-62
  idiom): star row preselected from `?rating`, optional comment, thanks state.

## 3. Read surfaces

- `GET /items/{item_id}/csat` (item.read; 404-quiet) → rating chip (stars +
  comment tooltip) in the issue rail once responded.
- Spec-63 `GET /reports/sla` buckets gain `csat_avg` / `csat_count`
  (responded_at-bucketed); the Service-desk report section shows a CSAT tile
  + trend line.

## Tests

Sender decision (setting off / no recipient / contact-over-reporter /
once-only), public submit flow (token 404, rating bounds, responded stamp),
report aggregation smoke.

## Known simplifications

- Email-only delivery (no in-app survey for registered reporters — they can
  open the public link like anyone).
- One survey per item lifetime; no reminder nudges.
- Rating links go through the SPA (no one-click GET mutation — the page
  POSTs), so mail scanners can't accidentally record ratings.

## As-built notes

- Migration `d90a8f7daa8a` (chained on `fb577d3807f9`): the `csat_surveys`
  table only. The autogenerate's usual `ix_doc_pages_fts` drop false-positive
  was stripped.
- Module loads LAST in RADD_MODULES (after mailintake — its `depends_on`
  includes the contact seam). New config: `RADD_CSAT_ENABLED` (the cascade's
  instance default, False) + `RADD_CSAT_POLL_SECONDS` (default 5s).
- **Resolve detection needs no workflow lookup**: `item.updated` payloads embed
  the full post-mutation `ItemRead`, whose `state` ref always carries
  `category` — `moved_to_done` (pure) just checks the diff touched `state` AND
  the embed's category is done. A done→done move (e.g. between two done states)
  also passes, harmlessly: the unique survey row keeps everything once-only.
- **Unlike mailintake.outbound, the sender WRITES in its poll transaction**:
  survey row + `csat.requested` + cursor commit together, before any SMTP I/O —
  so a crash mid-batch can lose an email but never double-create a survey, and
  a send failure leaves the row (that item is simply never surveyed; no retry
  queue, googlechat precedent).
- With SMTP or CSAT_ENABLED off the cursor still advances silently — enabling
  either later never surveys the backlog (only items resolving from then on).
- Both events are emitted with `actor_id=None` (not the SYSTEM actor): the
  requester has no user, and the automations engine's loop guard skips
  SYSTEM-actor events — None lets `csat.requested`/`csat.responded` rules fire
  (sla.breached precedent). Catalog rows live in a new "Service desk" group.
- `GET /items/{id}/csat` 404s for BOTH "no survey" and "sent but unanswered"
  (the spec's 404-quiet chip reading) — the response schema keeps
  rating/responded_at non-null.
- `csat.responded` payload carries the rating + a ≤200-char comment excerpt
  (comments-module precedent); `items/history.py` lifts `rating` into the
  History detail so the feed shows "recorded a 4/5 satisfaction rating".
- Reporting reads a **models-only seam** (`csat/report.py`, the `slas/report.py`
  idiom) because reporting loads before csat and cannot declare it in
  depends_on. The bucket asymmetry is deliberate and commented: SLA counters
  bucket by item-created week, csat by responded week.
- Frontend trend = an amber weekly avg-rating **BarChart** (not a line): weeks
  without responses naturally render no bar instead of a misleading dip to 0.
- Scoped-settings UI needed zero work — registering the BOOL key surfaces a
  checkbox on the existing instance/workspace/project settings editors.
