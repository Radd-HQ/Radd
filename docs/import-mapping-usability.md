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

## Follow-up implementation (RADD-1199 / RADD-1200)

The remaining Confluence destination controls are now implemented: existing space,
new space name, a searched/paged attribution account picker, directory group or
feature team for permission mappings, installed macro renderer, and the fallback
permission destination. Unused rows use the same editable controls. A background
plan refetch no longer overwrites the local draft. Save/check/run failures are
shown in the editor and action buttons are disabled while a request is pending.

Validation checks missing or deleted destinations and missing renderer plugins.
An incomplete explicit permission mapping blocks the page rather than falling
back to identity matching; an incomplete existing-space mapping cannot create a
new space. Ignored user mappings now stop before explicit-ID, email, domain and
name resolution. This affects author/mention matching, independently of page ACL
resolution. Page creation/version records still record an importing writer where
no source author resolves; comments retain nullable source authorship.

The browser proof selects/saves an existing space for an unused entry, a target
account, and a macro renderer, in addition to the previous Jira checks. Backend
checks cover ignored attribution and permission-safe mapping behavior.

## Import home and recovery review (RADD-1214)

Settings now has one **Import data** entry, with Jira and Confluence cards and
icons. Disabled importers link to Plugins; the existing importer URLs remain
valid. Each importer links back to the home. Confluence uses the same settings
frame and administrator presentation guard as Jira. Its Server/Data Center-only
compatibility is explicit; this change does not add Confluence Cloud support.

Confirmed problems fixed:

- Confluence run “Fix in…” links now select the run's original plan, then its
  mapping tab and source. Deleted plans have no misleading fix action.
- Editors remount when changing plans, preventing old editor state from being
  presented as the newly selected plan. Error jumps scroll after mappings load.
- Jira failed plan requests show the error rather than an endless spinner.
  Save/check/import actions share a busy state; edits clear stale validation.
- Confluence mapping search matches source and destination values and opens
  matching unused entries. Validation links filter to the named source.
- Confluence connection saves/tests/deletes, download operations, plan creation,
  run listing/cancellation, and undo preflight failures are now visible.
  Testing a non-default connection displays that connection's result.
- Confluence downloads offer a source connection. Space listing, recursive page
  browsing, query-cache identity, and snapshot creation all use that connection.
  Switching sources clears the previous source's selections.
- Both editors call the action “Save mappings” and explain that check/dry-run
  saves first. A dry run is a preview, not a guarantee that destination data
  cannot change before an import.

Validation: 131 backend importer tests passed (Jira pipeline, mapping,
connections, snapshots, inference; Confluence runs and storage conversion).
`web/scripts/import-mapping-proof.mjs` exercises source value translation,
existing destinations, unused mappings, save-before-check/run, mapping search,
and original-plan recovery in Chromium. TypeScript and production build passed.
Built-app browser verification also checked the import home, both icons,
legacy route, and download source selector. No company deployment or remote
source import was performed.

Remaining usability work worth a separate change:

- Protect unsaved mappings when navigating away or choosing another plan;
  currently Save mappings is explicit. Autosave needs conflict handling so two
  administrators cannot silently overwrite one another's plans.
- Reusable mapping templates and plan duplication across snapshots, with a
  review of missing source values and deleted destinations before reuse.
- A per-record comparison before replaying an import: mapping changes apply on
  the next run, and replay must not be presented as undoing a previous import.
- Confluence mapping catalogs still render all matches. For exceptionally large
  people catalogs, add incremental rows while retaining complete validation.
