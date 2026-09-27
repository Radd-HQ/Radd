"""The code-host connector kit (RADD-1435): everything GitLab, GitHub and Forgejo
have in common, bound to the `ConnectorSpec` each declares — `columns` (their
tables' shared columns), `schemas`, `store` (rows, audit, seed, webhook
resolution), `admin` (the admin router), `backfill` (the harness around the
connector's API walk) and `manifest` (what the plugin contributes, and which
connectors are loaded). The receiver's head and tail live in `vcs.receiving`."""
