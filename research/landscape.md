# Self-hosted Jira alternatives — 2026 landscape

Research date:

## Per-tool summary

| Tool | Stack | License / paywall gotchas | Custom fields | Plugins / API | AI (self-host LLM?) |
|---|---|---|---|---|---|
| Plane | Django + React/TS, PG/Redis/RabbitMQ/MinIO | AGPL CE + closed Commercial; **custom fields=Pro ($6/seat)**, workflows/automations/audit=Business ($13/seat), **LDAP/SCIM/air-gap=Enterprise**; all native integrations paid | Yes — Pro only; CE docs inconsistent on 12-user cap | No plugins; REST + webhooks in CE | Yes, BYOK incl. Ollama (best-in-class) |
| OpenProject | Rails + Angular, PG16+ | GPLv3 open-core; **SAML/OIDC/LDAP-sync paid**, project CFs, advanced boards, baselines, MCP paid | 10 types free on work packages; more paid | Rails-engine plugins, webhooks, HAL REST v3 + OpenAPI (best classic API); no GraphQL | Roadmap; MCP = Enterprise |
| Huly | TS + Svelte, CockroachDB/Redpanda/ES/MinIO | EPL-2.0, no paywall; but **cloud EOL July 2026 + blockchain pivot**; 10+ containers, 8–16GB RAM, manual migrations | Space types + custom attributes, free | Internal plugin platform; **no public REST API or webhooks** | aibot w/ any OpenAI-compatible URL |
| Taiga | Django + AngularJS 1.x, PG | MPL-2.0, no paywall; **maintenance-only since 2024** (successor: Tenzu by BIRU, AGPL, immature) | Free per-project, but can't filter boards by them | Webhooks + full documented REST | None |
| Leantime | PHP/Laravel + HTMX, MySQL | AGPL + proprietary-plugin carve-out; **custom fields = $39 plugin**, SAML $39, MCP $29 | Only via paid plugin | JSON-RPC only, no webhooks | Cloud-side only; paid MCP plugin |
| Redmine | Rails, multi-DB, ERB | **GPLv2, zero first-party paywall** | Free, per-tracker/project, rich; per-status field permissions; full transition matrix | Huge plugin ecosystem; REST partly alpha; no webhooks/GraphQL | Free community plugin `redmine_ai_helper` (provider-agnostic, MCP) |
| Gitea / Forgejo | Go single binary, any DB | Gitea: MIT + Enterprise (SAML/audit paid); Forgejo: GPLv3+, no paywall (anti-open-core hard fork) | **None** (open proposals since 2019: gitea#8665) | Webhooks, Swagger REST, Actions | None; Forgejo AI-skeptical |
| GitLab CE | Rails + Vue, PG/Redis/Go svcs | MIT CE / proprietary EE; epics, iterations, weights, multi-assignee, scoped labels, **custom fields (GA 18.0) all Premium+**; SAML group sync Premium | Premium+ only | No plugin system; excellent GraphQL+REST, webhooks | Duo Premium+; Duo Self-Hosted (vLLM etc.) |
| Focalboard | Go + React | MIT/AGPL; **unmaintained** (unbundled from Mattermost 2023) | Best-in-field per-board card properties (typed, groupable, view-driving) | Plugin-of-Mattermost only | None |
| Linear (SaaS benchmark) | TS/React/MobX/Node/PG | SaaS only | **No — deliberately** (label groups, form/intake fields instead) | GraphQL + typed webhooks + MCP + agent SDK | Native AI triage; agents as first-class users |

**Linear's sync engine** (the UX benchmark): client-side object graph in IndexedDB + in-memory MobX models, reversible transactions queued durably and batched as GraphQL mutations, server-side per-change SyncAction log broadcast as delta packets over WebSocket, one global monotonic `lastSyncId` as the entire consistency mechanism — **LWW per property, no CRDTs** (Yjs only inside the doc editor). Partial sync via `subscribedSyncGroups` + lazy hydration. Sources: https://linear.app/now/scaling-the-linear-sync-engine, https://github.com/wzhudev/reverse-linear-sync-engine.

## Lessons for building our own

1. **Non-paywalled auth is the single clearest market gap.** SSO, LDAP sync, SCIM, audit logs are paywalled in OpenProject, Plane, Leantime, Gitea Enterprise, GitLab. Ship free; market on it day one.
2. **Copy Linear's sync engine *shape*, not CRDTs**: monotonic change log, LWW-per-property, delta packets over WebSocket. Reserve Yjs for rich-text docs only.
3. **Plan partial sync from day one** if going local-first — retrofitting is the hard part of Linear's story.
4. **Custom fields: typed, filterable, view-driving properties in the free core.** The market splits into "none" (Forgejo, Linear), "paywalled" (Plane, GitLab, Leantime), "free but weak" (Taiga). Nobody ships Focalboard-quality properties in a maintained free tracker. Serialize inline, sync-friendly, filterable from the start.
5. **Constrain workflow like Linear** — fixed state categories (triage/backlog/unstarted/started/completed/canceled) with custom states inside — and add optional transition rules free (Redmine proves it's 20-year-old free tech; Plane charges $13/seat for it).
6. **Typed API + signed webhooks + MCP are table stakes.** Huly's fatal flaw is no public API. Most competitors paywalled their MCP — ship it free.
7. **AI-native means agents as principals, not a chat sidebar.** Linear's real innovation: agents as first-class assignable users with an interaction protocol + AI triage with auto-apply rules. No self-hosted tool has this. "Self-hosted Linear-for-Agents on Ollama" is an empty niche.
8. **Keep the deployable small: Forgejo-sized, not Huly-sized.** Loudest self-host community signal: love for single-binary + Postgres, resentment of 10-container stacks. Target one app container + Postgres; FTS before Elasticsearch; no broker.
9. **License against both failure modes**: open-core rug-pulls (Gitea→Forgejo; Plane feature migration) and abandonment (Taiga, Focalboard). AGPL + a public "never open-core" pledge is what burned users shop for. Monetize hosting/support — never auth, fields, or workflow.
10. **Steal Linear's product primitives**: auto-rolling cycles, triage inbox with routing rules, initiatives→projects→issues, views-as-saved-lenses.
11. **Intake forms beat generic custom fields for ~40% of demand** (Linear's finding): template-scoped form fields that don't pollute the issue schema. Offer both.
12. **Automations belong in core**, gated by rate limits not license.
13. **The forge gap is real**: Gitea/Forgejo users have wanted custom fields for 7 years — deep Forgejo/GitLab integration makes a standalone tracker viable for exactly the paywall-allergic audience.
14. **Speed is architected, then polished**: local reads, optimistic writes with client-generated UUIDs, keyboard/command-palette-first, code splitting. The client cache must exist first.

Key sources: https://plane.so/pricing · https://developers.plane.so/self-hosting/editions-and-versions · https://www.openproject.org/pricing/ · https://huly.io/blog/beyond-the-cloud · https://community.taiga.io/t/important-announcement-taiga-will-be-run-by-taiga-cloud-services/3112 · https://marketplace.leantime.io/product-category/plugins/ · https://about.gitea.com/products/gitea-enterprise/ · https://forgejo.org/2024-08-gpl/ · https://docs.gitlab.com/user/work_items/custom_fields/ · https://github.com/mattermost-community/focalboard · https://linear.app/developers
