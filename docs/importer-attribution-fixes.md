# Import mapping and attribution fixes

RADD-1194, RADD-1195 and RADD-1196 address three import failures reported on
2026-09-17. They are not a deployment or a repair of existing production data.

- Jira fields mapped to Team now provision/reuse teams from cached values and
  assign the resolved team on new and refreshed issues. Value translations are
  honored. Dry runs count each new team once without writing it. Rollback records
  team creation and previous issue assignment. Empty/unresolved values do not
  clear a manually assigned team. Importing team names does not grant membership
  or project access.
- An explicitly unknown imported comment author is stored as NULL and returned
  as `author: null`. Issue, page and inline comments display **Unknown author**.
  Ordinary writes still use the authenticated author; import overrides remain
  permission-gated. Known attribution is returned correctly in create responses.
  Jira comment failures roll back to a savepoint and become `comment_failed`
  problems rather than poisoning the whole transaction. Unknown public authors
  do not satisfy SLA response targets or imply an agent answered a requester.
- Two Jira source account keys can target the same normalized email. Provisioning
  and dry runs resolve both to one user. An existing user's name/settings remain
  unchanged; source keys stay distinct in the attribution mapping.

Apply migration `d1195commentauthor` with the application update. Clients consuming
comment JSON must accept a nullable author. A database downgrade back to mandatory
comment authors will refuse while unknown-author comments exist; it does not
silently delete comments or invent attribution. No historical authors are rewritten.

Verification: real-database importer regression tests cover team creation, refresh,
rollback, unknown Jira/Confluence authors, continued import after an SQL comment
failure, and merged-user attribution. Comment reader tests exercise null authors
and manager edits. `node web/scripts/import-author-proof.mjs` renders the actual
issue/page/inline components with an unknown author and checks anonymous access.

A retry is an operator action after deployment. These changes do not automatically
retry failed runs or change mappings on the company instance. Existing Jira comment
IDs remain deduplicated through the import ledger; Confluence retry behavior should
be reviewed against the affected run before repeating already completed stages.
