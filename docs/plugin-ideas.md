# Plugin ideas — future backlog

**Status:** not scheduled. These are example plugins a developer or the community might build on the
Radd plugin platform (`docs/plugin-platform.md`). We are **not building any of them now.** They are
kept for two reasons: (a) so the kernel is *designed to host them seamlessly* — each one was used to
stress-test the platform and the extension points they need are captured in `docs/plugin-platform.md`
§13; (b) as a candidate list to implement later.

Tier: **in-process** = trusted, admin-installed plugin (this platform). **sandbox** = belongs to the
separate untrusted-plugin track. All in-process ideas run under the mediation principle (§0.5) and the
permission-aware data SDK (§7.5) — they respect the acting user's permissions by construction.

| # | Idea | Tier | Integrates via | Key extension point it needs |
|---|------|------|----------------|------------------------------|
| 1 | **Two-way Slack / Teams chat-ops** — create/comment/transition issues from chat; notify back; slash commands + interactive buttons | in-process | notifier socket + inbound connector route + event consumers + data SDK (as the mapped user) | **credential vault + OAuth broker**; external-identity → Radd-user mapping |
| 2 | **OKRs / Goals** — objectives + key-results linked to issues, progress roll-up, own nav/pages | in-process | entity registry (cross-plugin FK to `item`), auto-wired events/RBAC/search, recompute-on-`item.updated` | none — the north-star case; validates cross-plugin FK + compute-on-event |
| 3 | **Formula / rollup field type** — a field computed from other fields, recalculated on change | in-process + frontend | new field *type* (validator + storage + widget) + compute-on-event | **field-type registry**; frontend federation for the widget (recompute dependency graph is hard) |
| 4 | **AI auto-triage & dedupe** — suggest labels/assignee, find duplicates, post a summary comment | in-process | AIProvider socket + data SDK + write-back + automation trigger/action + background task | **plugin/bot actor identity**; system-access escalation for cross-user reads |
| 5 | **Sprint-report / invoice PDF generator** — heavy render of items + worklogs into a downloadable PDF | in-process | TaskBackend + cross-module data SDK + StorageBackend socket + download endpoint | confirms StorageBackend + TaskBackend; artifact-download pattern; optional-dependency degradation |
| 6 | **Celery task backend** — swap the poll-loop runner for Celery/Redis | in-process (infra) | TaskBackend socket only | none — the acceptance test for the TaskBackend abstraction (§6) |
| 7 | **Attachment antivirus / DLP filter** — scan every upload; quarantine/reject before storage | in-process | synchronous, ordered, *vetoing* hook on the upload path | **pipeline / interceptor registry** (new shape: not post-commit events, not in-txn hooks) |
| 8 | **SCIM / SAML provisioning** — auto-provision/deactivate users & teams from an IdP; new login method | in-process (privileged) | auth-method registry + privileged provisioning API, under system-access | **auth-method registry + provisioning API**; heavy use of the capability-manifest gate + audit |
| 9 | **GitHub / GitLab deep two-way sync** — issues ↔ items, status/label/assignee sync, PR links | in-process | inbound connector + outbound egress + plugin-owned mapping tables + reconcile task + credential vault | **bulk-ingest + external-ID mapping helper**; idempotency/conflict tooling (bidirectional is real product design) |
| 10 | **Prometheus metrics / audit → SIEM exporter** — expose `/metrics` or push audit to a SIEM | in-process (read-only) | event-stream consumer + egress | **route outside `/api/v1` (+ unauthenticated)**; declared egress |

## Honorable mentions (each exposes one more seam)

- **Customer portal / public status page** → **anonymous/portal security context + public routes + rate limiting**.
- **Google Calendar two-way (per user)** → **per-user OAuth token storage + per-user scheduled tasks** (cron/fan-out).
- **No-code admin scripting** → the poster child for the **sandboxed tier** — untrusted admin-authored logic; belongs to the separate track, *not* in-process.

See `docs/plugin-platform.md` §13 for the consolidated list of extension points these require and their
build priority (design-for-now vs. build-when-first-needed).
