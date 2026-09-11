# Field scope-change authority — 2026-09-10

RADD-1115 follow-up found while tracing the remaining field settings directory and capability gaps. Full research remains in progress.

## Defect and correction

`PATCH /fields/{id}` previously merged current and requested project IDs before checking `field.update`. An empty field scope means **global**, so a set union erased a required global check in either direction. A project-only editor could promote a scoped field to global by submitting `project_ids: []`, or narrow a global field to a project they controlled. An instance-admin API key narrowed to project-only field.update had the same exposure.

The router now authorizes the current scope first, then the requested scope independently when a replacement list is provided. Every project on each side must be authorized; either global side requires global field.update. Both checks run before the owner service changes the definition. Omitted or null project_ids retain the existing scope. Granular field.update does not confer create, delete or grant-management authority. No schema migration is needed.

## Verification

The new real HTTP/database regression file, `server/tests/test_field_scope_authority.py`, covers:

- Project-only browser sessions and project-scoped admin keys: scoped → global, global → scoped, unchanged global, unauthorized destination, and removing an uncontrolled current project all return 403. SQL readback proves that neither scope rows nor a simultaneously submitted name were changed.
- Authorized presentation edits, null/omitted scope, expansion across managed projects and narrowing/moving within those projects succeed.
- An admin key narrowed to global field.update can cross the global boundary but cannot delete a field. Project-only update actors cannot create, delete or manage access grants.

[Focused checks](focused-tests.txt): 36 passed, including existing field-scope, grant, option and generic grant-directory tests. [Full backend suite](backend-tests.txt): **2,470 passed, 4 skipped**, 150 warnings, 110.89 seconds. Runtime and new-test Ruff checks plus `git diff --check` pass. Frontend source is unchanged; the prior full frontend/plugin build remains the current build. [Populated API/LLM/storage/search](live-api.json), [grant readback](live-grants.json) and [read-only field-editor browser](live-fields-browser.json) pass; the latter covers public person choices and nested focus/bounds at 390/768/1440 px. All mutation evidence uses the disposable database; populated checks are read-oriented.

## Remaining work

This security correction does not close P2. Field settings still needs bounded field/project catalogs, per-definition create/update/delete/grant capabilities, admission for scoped-only field administrators and permission-filtered scope choices. The field scope UI must respect global authority when offering global transitions. Complete issue properties/comment team reads, service-account/key lists/counts, other readers, cycle scans, authority maps and every broader research outcome remain open. No frontend source changes or external deployment were made in this checkpoint.


[Populated general browser](live-browser.json) also passes. Both development databases retain 503,485 / 8,923 issues and schemas g1093ghost / d117pkg. Workers-disabled app18000 now runs PID2009843 with health200. No disposable app is running; temporary session revoked and private cookie file removed. No migration, commit, push, release or hosted CI activation occurred. See [environment evidence](environment.json).
