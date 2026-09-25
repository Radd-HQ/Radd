# RADD-1340 — Plugin disabling and dependent UI

GitHub and Forgejo were saved as disabled in the local database but were still loaded in the running backend. Backend-bearing plugins intentionally require restarting web and worker processes: unloading their routes, tasks, and hooks safely is not supported by the current live reconciler. The UI showed the desired state as “Disabled” while runtime state remained active. Separately, Version Control deliberately retained every provider tab, and the automation catalog/templates were cached indefinitely.

The Plugins page now distinguishes Enable pending / Disable pending from applied state, shows a visible restart notice, explains what remains active, and offers Cancel enable / Cancel disable for pending choices. This does not claim that backend plugins unload live. Version Control only lists loaded providers, falls back from a stale provider URL to an available one, and shows an empty state when none are loaded. It waits for the capability manifest before querying a provider. The shell invalidates automation metadata when the loaded plugin set changes, including inactive cached queries; lifecycle actions also invalidate it.

The local backend was restarted with the user's existing settings. Its capability response now lists only GitLab among VCS providers, and its OpenAPI schema contains no GitHub or Forgejo routes. Saved connections and automations were not deleted or rewritten. No production configuration, release, or deployment was changed.

Validation:

- TypeScript and production frontend build passed.
- All 33 frontend unit tests passed.
- Existing plugin-management browser proof passed (upload, install, pending activation, failures, and retained data).
- New built-SPA browser regression, using a controlled API fixture, covers pending-disable messages, provider removal after runtime changes, old provider links, catalog/template refresh without reload, absent disabled palette groups, and the all-disabled empty state. Added to `npm run test:browser`.
- Actual local health, capability manifest, and route removal were checked separately against port 8000.
