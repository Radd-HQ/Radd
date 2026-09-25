# RADD-1341 — Restart-free installed plugin toggles

Installed plugins now enable and disable live. The same lifecycle handles GitHub, Forgejo, other optional built-ins, and installed external plugins; core plugins remain protected. Installing/upgrading Python code remains separate.

Each process reconciles committed desired state, stops admissions to the changing plugin, pauses new periodic ticks, and drains admitted HTTP requests and tracked jobs before changing the registry. Unrelated HTTP requests remain available while draining. Startup/shutdown hooks and scheduled loops belong to the plugin, routes are inserted before fallback routes and removed on disable, generated entity contributions are withdrawn, and exception handlers and OpenAPI follow runtime state. Plugin WebSockets close during disable and shutdown hooks flush pending state. Configuration, stored entities, and saved automation graphs remain intact.

Database process reports include the active set, observed desired state, and the version of each saved choice. The UI shows Applying until every live process acknowledges that exact change; older acknowledgements cannot complete a newer toggle. Failures remain visible and retry. Process leases expire after 30 seconds; local HTTP/periodic admissions stop after 25 seconds without renewal, and WebSockets reject new connections/messages after expiry. Process identities are created after forking. Package file removal retains its existing conservative filesystem checks.

Long-running work is never cancelled to force a normal disable through. A drain timeout leaves the change unapplied with a retryable error. Plugins must own and stop their background resources, use PeriodicLoop or TaskSpec for recurring work, and use the tracked spawn helper for request-spawned jobs. Jira/Confluence import and snapshot jobs now use that helper. This is not Python module hot-reloading.

Validation:

- Full backend suite: **3,150 passed, 4 skipped**.
- Final focused run after acknowledgement-version and WebSocket lease refinements: **80 passed** (runtime, manager, package lifecycle, code hygiene, collaboration).
- **33 frontend unit tests passed**; TypeScript and production frontend build passed.
- Built-SPA plugin-management and availability browser checks passed, including Applying status, removal of unavailable tabs/nodes and catalog refresh without page reload. Screenshots inspected.
- Actual local API verification on final backend PID **1912892**: enabled and disabled GitHub, then Forgejo; routes and automation triggers appeared/disappeared without changing that PID. Both were restored to disabled and temporary verification credentials were removed.
- Ruff and whitespace checks passed.

Migration `d1341liveplugin` adds leased process acknowledgements. Applied locally; final code is running on port 8000. No push, release or production deployment performed.
