# Access-control hardening (RADD-1213)

The September review found inconsistent authorization between primary resource routes and secondary readers, background delivery, and intrinsic owner actions. This change aligns those surfaces with the existing resource, row, space, and credential policies.

## Changed behavior

- Wiki MCP, exports, backlinks, issue documentation links, attachment reads, and search suggestions respect the caller's space and page restrictions. Creating or moving a page requires access to its destination parent.
- The raw `/events` feed requires `global.manage`. Project managers use the scoped, redacted audit API.
- Scoped API keys cannot exceed their configured rights through team ownership, view/dashboard sharing, approval eligibility, participant management, or leave ownership. Dashboard keys have separate `dashboard.update` and `dashboard.delete` scopes; those scopes alone do not confer ownership. Leave changes require a browser session or an unscoped full-access key.
- Supplemental issue writes enforce row qualifications. MCP work logging also requires `worklog.write`.
- Immediate and digest email recheck live resource and comment visibility before composing mail. Ineligible messages are stamped without delivery. Previously delivered messages and historical inbox entries are not recalled.
- An allow-list restriction survives its final grant's revocation or expiry. Administrators explicitly use **Restore parent access** to remove that access level's allow list. Explicit denies remain. Owners/managers retain the intrinsic rights defined by each resource.
- Saving global role holders preserves retained grants, expiry, attribution and directory-group subjects. Full-list saves require `expected_grant_ids`; stale saves return a conflict. Clients should reload and reconcile.
- Role dialogs require an explicit scope, support expiry, and filter delegated project-role choices by coverage. Existing readable role references can still resolve by ID without granting assignment authority. Expiry can be changed from the grant lists.
- The inspector includes Anyone/Signed-in sources and checks role scope for wiki and attachment rules. It describes grant sources, not a promise that other restrictions permit an operation. Team membership controls show the number and scope of directly attached role grants and resource rules.

## Migration and rollout

Run `alembic upgrade head` before starting the updated application. Migration `d1213access` adds durable restriction records and backfills existing allow grants, including expired grants. Existing resources whose grants were already deleted before this migration have no recoverable restriction evidence; administrators must recreate those intended restrictions from their records.

Review scoped integration keys for the newly enforced write requirements. Do not broaden a key beyond the actions its integration needs. Existing browser ownership workflows remain available.

Missing AD groups retain memberships under the existing directory policy. The management screen now states when the group went missing and that access remains. Restore a renamed group's directory identity, or explicitly revoke its grants and remove team links for a deleted group. Review deny rules before removing membership; automatic removal can inadvertently remove a denial. Live AD synchronization, production mail/storage integration, and multi-process deployment behavior still require company-instance testing.

Operational permissions deserve particular care: automation can execute through the system actor; webhooks export event payloads; publishing/sweeping releases can transition matching issues. Their administrative authority is broader than editing a label or display name.

## Verification

Regression coverage lives in `test_authorization_surfaces.py`, `test_authorization_grant_lifecycle.py`, and `test_access_management_hardening.py`, alongside the existing policy and management suites. Browser proofs cover explicit global-scope selection and restoring a durable page restriction. The proofs use an authenticated local session and clean up their disposable wiki space.

This change is intended for the next release. It is not evidence that the company deployment has already been upgraded or that every external integration has been exercised.

Validation for RADD-1213: full backend suite **2,775 passed, 4 skipped**; final focused checks **76 passed** after the last credential/delivery refinements; frontend tests **21 passed**; TypeScript, production build, Ruff and diff checks passed. Browser proofs passed six grant-dialog checks and three restriction-reset checks. Production build retains the existing bundle-size advisory.
