# Import mapping usability sweep — RADD-1198

Jira mappings now label actions and destinations. Existing status and issue-type
mappings select from the target project's catalog; status selection carries its
reporting category. Field destinations show the field name and key. Select-field
and native-team mappings expose source-to-target value translations, with existing
values offered first and an explicit custom-value option. Large value catalogs
are filtered and progressively expanded. Field rows are memoized and indexed;
comma-separated option input preserves partially typed delimiters.

Validation reports missing existing status/type targets. Provisioning also refuses
to silently create them. Option extension uses translated target values, deduplicated,
instead of adding the raw Jira values back into the destination catalog.

Confluence Check saves the current draft before validation. Dry run and Import
save within their mutation before starting; this also keeps save failures on the
mutation error path. Mapping actions now have a visible label.

Verification: `web/scripts/import-mapping-proof.mjs` renders the actual editors
with a 337-field catalog, selects and saves existing state/field/team destinations,
and checks Confluence save-before-check/run request ordering. Backend regressions
cover missing MAP targets and translated option extension. This is a functional
browser check, not a production performance benchmark.

Remaining sweep findings, saved as work items:

- RADD-1199: Confluence explicit destination pickers and editable unused entries.
  Its current generic rows mostly expose the action alone.
- RADD-1200: Confluence Leave unattributed is not honored by `_people`; identity
  resolution can still match an explicit ID, email or display name. Fix and test
  this before relying on that option during the internal import trial.
- RADD-1201: Other grouped boards and service queues need ordering before paging;
  sorting a loaded page cannot surface urgent work from later pages.

These changes are local and await release. The deployed Emden instance has not
been updated or used for these tests.
