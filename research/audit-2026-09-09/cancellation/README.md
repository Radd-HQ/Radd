# Request cancellation — RADD-1115, 2026-09-10

P4 is verified locally, not released. TanStack query functions pass their AbortSignal through GET, paged GET and read-only POST requests in the host and plugin remotes. The plugin SDK forwards that signal to fetch. SLQ suggestions cancel immediately on new input, close, project/dialect change and unmount; a sequence guard prevents an obsolete response from replacing the current suggestion state.

`web/scripts/query-cancellation.test.mjs` executes the actual API and query factories with real QueryObservers: obsolete searches, closed readers and infinite next-page requests abort; removing one of two readers preserves the other's request. It covers the separate plugin SDK too. `browser-smoke.mjs` observes actual HTTP disconnects for superseded and closed command-palette searches in the built SPA. `browser-autocomplete.mjs` mounts the actual React hook and observes HTTP disconnects for typing, close, scope/dialect changes and unmount, including the new scope and dialect in replacement URLs.

The saved `npm run check` output includes all seven JavaScript test files, the host and six plugin remotes, and both Chromium checks passing. Network cancellation does not promise rollback of server work already accepted; write mutations retain their existing semantics.
