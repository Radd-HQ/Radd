# Radd frontend dead-code audit — `web/`, 2026-08-05

All paths relative to ``. Scope grepped for every claim: `web/src`, `web/packages`, `web/scripts`, `server/src/radd/modules/*/ui`, `examples/acme-notes`. `web/packages/plugin-sdk`'s public API was exempted as instructed (it came out clean anyway — every SDK export is index-re-exported).

## Executive summary

| Category | Findings | Est. deletable lines |
|---|---|---|
| 1. Unused components | **0** of ~250 component files | 0 |
| 2. Unused exports (full deletions) | **~52 symbols** across lib/, queries/, components | ~330 |
| 2b. Unnecessary `export` keywords | ~90 symbols (definition stays, keyword goes) | 0 (hygiene) |
| 3. Unlinked / legacy routes | 8 legacy redirect routes + entries | ~105 (policy call) |
| 4. Dead props | **0** confirmed (method + `noUnusedLocals` coverage) | 0 |
| 5. Refactor leftovers | RADD-701 fixed; ~4 stale comments; the dead exports below ARE the leftovers | — |
| 6. Unused CSS | 1 dead rule family (with a live-bug smell) + 2 dead tokens + 2 suspect | ~25 |
| 7. Unused assets | **5 SVGs** in `public/brand/` | 5 files |
| 8. Unused npm deps | **0** — every dep and devDep is imported | 0 |
| 9. Unused types | **16 interfaces/aliases** fully dead (12 files) | ~120 |
| 10. Stale proofs | 1 vacuous selector; 2 deliberate absence-assertions (fine) | — |

**Total: ~580 deletable lines + 5 asset files.** The headline pattern: almost nothing whole-file is dead — the debt is *exports orphaned by completed refactors* (views-only pages, spec-92 access grants, spec-100 Jira rebuild, plugin remotes self-fetching).

---

## 1. Unused components — none

Every `.tsx` under `web/src/components` has ≥1 real importer (verified including bare side-effect imports — `pages/extensions.tsx` looked dead until `import "../pages/extensions"` in `ExtensionNodeView.tsx:13` turned up). `router.tsx` lazy imports checked. No component's sole importer is a proof script or a dead file.

## 2. Unused exports — full deletions (CERTAIN unless marked)

**Query factories, `web/src/lib/queries/` — zero call sites anywhere.** Each is a leftover of a surface that moved (plugin remotes self-fetch; builtin board/list pages deleted; spec-100 rebuilt the Jira wizard):

| Export | Location | Note / chain scope |
|---|---|---|
| `itemApprovalsQuery` | `queries/approvals.ts:24` | approvals UI is a plugin remote now; delete `queryKeys.itemApprovals` + `apiItemApprovalsPath` (`constants/api-paths.ts:142`) with it |
| `participantsQuery` | `queries/approvals.ts:44` | participants remote self-fetches (documented in CLAUDE.md); chain: `queryKeys.itemParticipants`, `apiItemParticipantsPath`/`apiItemParticipantPath` (`api-paths.ts:147-150`) |
| `infiniteItemsQuery` | `queries/items.ts:43` | views-only refactor leftover (builtin List page deleted) |
| `itemQuery` | `queries/items.ts:60` | everything resolves by key now (`itemByKeyQuery` is alive) |
| `itemCsatQuery` | `queries/forms.ts:110` | chain: `queryKeys.itemCsat`, `apiItemCsatPath` (`api-paths.ts:139`) |
| `mailContactQuery` | `queries/forms.ts:79` | chain: `queryKeys.mailContact` |
| `jiraRunQuery` | `queries/jira.ts:105` | pre-spec-100 wizard polling |
| `jiraSnapshotQuery` | `queries/jira.ts:72` | chain: `queryKeys.jiraSnapshot`, `queryKeys.jiraRun` |
| `pageTemplatesQuery` | `queries/pages.ts:90` | chain: `queryKeys.pageTemplates` |
| `screenConfigQuery` | `queries/projects.ts:111` | `queryKeys.screenConfig` has other users — keep the key |

**`web/src/lib/meta.ts`** (629 lines, checked exhaustively) — six constants defined and never read, in file or out:
- `FIELD_ACCESS_LABELS` (:241), `FIELD_ACCESS_ORDER` (:246) — spec-92 replaced the field-permission editor these fed
- `INSTANCE_ROLE_ORDER` (:257)
- `VIEW_TYPE_LABELS` (:263) — view-type labels now come from the kernel view-type registry
- `LINK_TYPE_LABELS` (:360), `LINK_TYPE_ORDER` (:367) — spec 91 made link types DB rows; the hardcoded table is exactly the thing that spec deleted server-side

**`web/src/lib/hooks.ts`** (586 lines, exhaustive): no dead functions — only 5 type exports needing just the keyword dropped (`ItemByKey`, `ItemWritability`, `ProjectByKey`, `SlqAutocomplete`, `SlqProbeStatusValue`). **`web/src/lib/view-utils.ts`** (502 lines, exhaustive): no dead code — 9 keyword-only exports (`AxisContext`, `BACKLOG_LABEL`, `cfAxisToken`, `isCfAxis`, `matchesCycleFilter`, `NO_EPIC_LABEL`, `NO_TEAM_LABEL`, `NO_VALUE_LABEL`, `UNASSIGNED_LABEL`).

**Rest of lib/ + components — fully dead (definition + all its lines):**

| Export | Location | Evidence |
|---|---|---|
| `useMoveItem` | `lib/item-mutations.ts:73` (~35 lines) | optimistic board-column DnD hook, zero callers — views-only refactor leftover; shared helpers above it stay (used by `useUpdateItem` etc.) |
| `remoteStates` | `lib/plugin-loader.ts:39` | "diagnostics" fn, never called |
| `reloadPluginRemote` | `lib/plugin-loader.ts:116` | disable→enable is handled by `syncPluginRemotes` |
| `iconNames` | `lib/icons.ts:139` | |
| `DEFAULT_PLANNING_SLOTS` | `lib/card-display.ts:116` | spec-109 card designer superseded the slot system's planning default |
| `titleWidthOf` | `lib/columns.ts:34` | |
| `AuthStatusValue` | `lib/auth.ts:20` | |
| `SlqDialectValue` | `lib/slq-suggest.ts:28` | |
| `apiApprovalPath`, `apiApprovalVotePath` | `lib/constants/api-paths.ts:143-144` | approvals writes moved to the remote |
| `apiFieldPermissionsPath` | `lib/constants/api-paths.ts:106` | spec 92 dropped `field_permissions` — this is the wire-constant leftover of that migration |
| `apiItemParticipantPath` | `lib/constants/api-paths.ts:149` | |
| `ApiPathValue` | `lib/constants/api.ts:188` | |
| `apiReleaseSweepPath` | `lib/constants/api.ts:223` | sweeps go over MCP now |
| `apiServiceAccountPath` | `lib/constants/api.ts:217` | |
| `EpicProgressBlock` | `components/items/RollupBar.tsx:56` (~41 lines) | "issue view's Epic progress block" — never rendered anywhere |
| `selectionInsideNode` + `export { StreamLanguage }` | `components/editor/code-block.ts:268, :275` | |
| `EXTENSION_TOOLBAR_ICON` | `components/editor/ExtensionPicker.tsx:45` | |
| `xFromDay` | `components/roadmap/model/geometry.ts:103` | |

**2b. `export` keyword removals** (used in-file only; ~90 symbols — worth one sweep commit): the hooks/view-utils lists above, plus `columns.ts` (`BUILTIN_COLUMNS`, `COLUMN_MIN_WIDTH`, `DEFAULT_*_COLUMNS`, `TITLE_*`, `ColumnWidthsState`), `card-cells.tsx` (`EpicChip`, `PriorityTag`, `QuietLabels`), `pages/extensions.tsx` (`Backlinks`), `DisplayMenu.tsx` (`CardDesignerEntry`, `ColumnsEditor`), `SidebarRail.tsx` (`railButtonClasses`), all the roadmap `*Props`/plan types, the editor `ai-run`/`toolbar-state`/`chips`/`image-width`/`diff` internals, ~40 `*Value` companion types in `lib/types/*`, and `RouterContext` (`router.tsx:87`). None of these change bundle size, they just stop lying about the public surface.

## 3. Routes — legacy redirects (LIKELY deletable; policy call)

Nothing links to these; they exist purely so pre-rename URLs redirect. Under "no backcompat until V1" they are deletable ceremony — **but** project.radd-hq.com is public and old `/kb/*` links may live in the wild (the server mints no `/kb` or `/docs` links today — verified). Recommend: delete the `/docs` + members + leave set (internal URLs only), decide consciously on `/kb`:

- `router.tsx:131-158` — `legacyKb`, `legacyKbSpace`, `legacyKbPage` (+ `RoutePath` entries `constants/routes.ts:203-205`)
- `router.tsx:349-375` — `legacyDocs`, `legacyDocSpace`, `legacyDocPage` (+ `routes.ts:196-198`)
- `router.tsx:457-466` — `settingsMembersRoute` (+ `SettingsSection.members`, `routes.ts:28`)
- `router.tsx:589-596` — `settingsLeaveRoute` (+ `SettingsSection.leave`, `routes.ts:60`)

**Unlinked-but-alive** (listed, not dead): `RoutePath.pagePrint` — opened via hand-built string at `components/pages/PageView.tsx:147`, never via the constant; `RoutePath.publicCsat` — URL minted server-side (`csat/types.py:51`); `RoutePath.roadmap` — legacy redirect that IS still used by `CommandPalette.tsx:200`.

## 4. Dead props — none found

Systematic scan (every `*Props` member, whole-repo word-grep, common names excluded) surfaced one candidate — `canReorderHere`/`onReorderOver` in `ViewList.tsx` — which is a false positive (passed to the row subcomponent in the same file, :287-289). Boolean shorthand passing (`extraWide`, `frameless`, `numeric`) was specifically re-checked after the first pass missed it. `noUnusedLocals`+`noUnusedParameters` are on, which structurally prevents most "passed but never read" cases.

## 5. Refactor leftovers — the renames were finished; the stale bits are comments

- **RADD-701's four leftovers (`doc_page`, `/docs/search`, 2× `/public/kb/*`): all fixed.** Only history-explaining comments remain (`lib/types/attachments.ts:9`, `lib/types/pages.ts:185`).
- **Crepe**: zero code references. ~40 comment mentions (legitimate history) + proof scripts asserting Crepe chrome is *absent* (correct). Two genuinely stale: `components/editor/rich-editor.css:157` — "RADD-754 removes Crepe's stylesheet entirely; **this block goes with it**" sits on a block the preceding sentence (:148) says was deliberately **kept**; the trailing sentence is a pre-decision leftover that now instructs a wrong deletion. And `components/editor/mention.ts:39` — "Added via `crepe.editor.use(...)`" describes an API that no longer exists.
- **`index.css:33-34`** — "~all components hardcode zinc-* and indigo-* utilities" is false since the Dusk wave (zero raw zinc/indigo in `web/src`); the remap comment should say the *semantic tokens* consume the scale.
- **ProjectNav / MinIO / workspace scope / builtin board-list-planning pages**: zero references in `web/`. Clean — except the orphaned exports in §2 (`useMoveItem`, `infiniteItemsQuery`, `itemQuery`) which are the views-only refactor's frontend residue.

## 6. Unused CSS

- **CERTAIN + bug-adjacent** — `components/editor/editor.css:184-194`: rules for `.milkdown-diff-insert`, `.milkdown-diff-block-insert`, `.milkdown-diff-delete`, `.milkdown-diff-block-delete`. The forked decoration plugin emits **`milkdown-diff-added` / `-added-block` / `-removed`** (`diff/decoration-plugin.ts:239,314,354-356`) — the styled names are never emitted, and the emitted names are styled **nowhere**. Dead CSS whose deletion should prompt a check: non-textblock deletions currently get `-removed` with no strikethrough styling at all.
- **CERTAIN** — `index.css`: `--color-zinc-50` (:247, :333) and `--color-zinc-300` (:244, :330) — no `var()` reference, no utility use, not fed into any semantic token (verified per zinc step).
- **LIKELY** — `--chart-backlog-ink` and `--chart-canceled-ink` (+ their `--color-chart-*-ink` bridges, `index.css:182,186`): `text-chart-backlog-ink`/`-canceled-ink` never appear. Kept only for six-token set symmetry; your call.
- Everything else that greps "unused" in `editor.css` is vendor-runtime (`.ProseMirror-selectednode`, `.column-resize-handle` from prosemirror-tables, `.milkdown-list-item-block`/`.label-wrapper`/`.content-dom` from the kit's components, `.link-preview`/`.link-edit` from linkTooltip) — **alive, do not delete**.
- `rich-editor.css`, `page-print.css`, plugin-sdk `tokens.css`: fully consumed.

## 7. Unused assets — `web/public/brand/`

CERTAIN (zero references in repo, incl. server + README): `app-icon-dark.svg`, `app-icon-finger.svg`, `app-icon-finger-dark.svg`, `mark-outline.svg`, `mark-solid-finger.svg`. Ship in every deploy for nothing.
SUSPECT: `mark-solid.svg` — runtime-unreferenced but named as the canonical source of `RaddMark.tsx`'s inline copy (:3, "keep the two in sync"). Keep or move next to the component. `app-icon.svg` is used by `README.md:1`; favicons + `/shared/*` + fonts all referenced.

## 8. npm dependencies — clean

All 17 `dependencies` and all 7 `devDependencies` in `web/package.json` are imported (`vite.config.ts` accounts for `@tailwindcss/vite`/`@vitejs/plugin-react`; `typescript`/`@types/*` are toolchain). Nothing to remove.

## 9. Unused types (full deletions, CERTAIN)

`lib/types/jira-import.ts` (513 lines, checked exhaustively): the **pre-spec-100 wizard block is dead** — `JiraPreview` (:193-197) and the contiguous `ValidateMappingsResponse` + `ImportPlan` + `ImportStage` + `ImportStageValue` + `ImportRun` (:472-513, ~42 lines; the latter three are a chain — only `ImportRun` references `ImportStage*`). `DryRunRow` stays (used at :449).

Elsewhere: `TeamUpdate` (`teams.ts:41`), `ProjectTeamUpdate` (`teams.ts:228`), `UserCreate` (`users.ts:117`), `FieldDefUpdate` (`fields.ts:112`), `FieldSubject`+`FieldSubjectValue` (`fields.ts:21-25`, a dead pair), `TransitionCheckValue` (`workflow.ts:72`), `EmailRecipientValue` (`automations.ts:132`), `BackupKind`+`BackupKindValue` (`backups.ts:4-10`, dead pair), `RunStatus` (`backups.ts:19`), `WebLinkUpdate` (`integrations.ts:32`), `LinkTypeUpdate` (`link-types.ts:36`), `ResourceGrantSpec` (`grants.ts:40`).

## 10. Proof scripts (`web/scripts/`)

- **Stale-proof (vacuous)** — `page-print-proof.mjs:136`: `hasTree: !!document.querySelector("[data-page-tree]")` — `data-page-tree` exists nowhere in `web/src`, so the "print view has no page tree" assertion passes unconditionally, exactly the vacuous-check class CLAUDE.md warns about. (`:134`'s `data-top-bar` is also unset anywhere, but its `nav[aria-label='Primary']` fallback is real — `SidebarRail.tsx:82`.) Fix: give PageTree the attribute or assert on something it renders.
- **Fine, deliberately** — `editor-toolbar-proof.mjs:67` (`.milkdown-top-bar`) and the other `crepe*` selectors assert *absence* of removed Crepe chrome; `.cm-line` in `code-block-proof.mjs` is CodeMirror-runtime. No proof references deleted UI it needs to be *present*.
- `anchoring.test.mjs` / `line-diff.test.mjs` import live lib files; `build-all.mjs`/`prepare-federation.mjs`/`gen-shared-shims.mjs` are the build pipeline.

---

**Recommended deletion order** (per the systemic-fix preference): (1) one commit for the query-factory + queryKeys + api-path chain (§2 table, ~170 lines — it's one refactor's residue); (2) one for meta/types/misc dead exports (~250 lines); (3) the CSS + assets + stale comments (~30 lines + 5 files), folding in the `milkdown-diff-added/-removed` styling check; (4) a decision commit on the legacy routes (~105 lines); (5) optionally the export-keyword sweep. `tsc -b && vite build` after each — every deletion here is import-graph-verified, so the build is the regression check.
