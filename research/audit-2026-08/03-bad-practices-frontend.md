# Radd frontend bad-practices audit — `web/src`

Read-only audit against CLAUDE.md "Frontend conventions" + "Verifying UI work". ~78k lines of TS/TSX across 4 CSS files and ~340 components/routes. 2026-08-05.

## Executive summary

| Category | Findings | Worst severity |
|---|---|---|
| 1. Token violations | 10 distinct violations (+1 systemic pattern, ~610 raw status-palette occurrences) | **High** — the issue-rail state chip contradicts the design system's traffic-light colors |
| 2. Kit bypasses | 0 native `<select>`, 0 `window.confirm/alert` (clean); 46 hand-rolled secondary-button lookalikes, 34 copies of one icon-button class, 1 hand-rolled inline confirm, ~6 hand-rolled popover/combobox dropdowns | Medium |
| 3. React hazards | 8 files keying removable rows by index; 8 documented `exhaustive-deps` suppressions (all justified); pagination/virtualization hygiene is good; no controlled/uncontrolled mixes | Medium |
| 4. Data fetching | Centralized and disciplined; 3 raw `fetch` sites (2 justified), 2 swallowed catches (both deliberate) | Low |
| 5. Accessibility | Strong baseline (aria on nearly everything); no focus trap in Modal, one keyboard-unreachable picker, opacity-dimmed text in 3 places | Medium |
| 6. Duplication | form routes ~60% identical; 4 copies of the directory chip; 109 ad-hoc error `<p>`s; date formatting scattered across 13+ sites beside `lib/dates.ts` | Medium |
| 7. Type safety | Exemplary: 1 `as any`, 1 `as unknown as`, 0 `@ts-ignore` in 78k lines | Info |
| 8. Dead CSS | 2 dead theme tokens, 1 stale selector | Low |
| File size rule | 64 files exceed ~300 lines (top: `routes/view.tsx` 1323) | Info |

The two headline verdicts: **the zero-`zinc-*`/`indigo-*` rule still holds in markup** (only the sanctioned `index.css` remap and comments mention them) — but **indigo survives as hex constants** in the chart/roadmap layer, and the issue rail carries a **drifted second copy of the workflow-state palette** that paints In Progress yellow where the entire rest of the product paints it green.

---

## 1. Token violations

The sanctioned mechanism (from `web/src/index.css:384-398`): status colors are raw Tailwind utilities (`text-red-400`, `text-amber-300`, …) whose **specific shades** are remapped per theme. Remapped shades: amber-200/300/400, emerald-300/400, red-300/400, sky-300, purple-300, teal-300, violet-300. Anything outside that table renders Tailwind's stock value in both themes — the exact failure mode the file's own comment documents ("pale pastels on white, ~2:1"). ~610 raw palette-utility occurrences across ~44 distinct utilities ride this mechanism.

**High — a second, drifted copy of the workflow-state palette.**
`web/src/components/items/IssueProperties.tsx:22-35`
```ts
const CATEGORY_CHIP: Record<string, string> = {
  triage: "#f59e0b", backlog: "#71717a", todo: "#3b82f6",
  in_progress: "#eab308", done: "#22c55e", canceled: "#52525b",
};
```
`index.css` declares `--chart-*` as "ONE source of truth for the state dots, the state pills, the roadmap bar fills and every report series." This map was missed: `in_progress` is **yellow** (#eab308) where the system's traffic-light reading makes it **green** (`--chart-progress` #26804a); `done` is green (#22c55e) where the system makes it slate; `triage`/`backlog` also differ. The state chip on the issue rail — the single most-viewed chip in the product — contradicts the board, the roadmap and every report. Also theme-blind (same hex in light). `PRIORITY_CHIP` below it is the same pattern. Fix: `ValueChip` should take `var(--chart-<category>)` / a priority token, delete both maps.

**High — chart constants pinned to the pre-Dusk indigo accent, theme-blind.**
`web/src/lib/meta.ts:401-409`
```ts
export const BURNUP_SCOPE_COLOR = "#818cf8"; // indigo-400
export const CHART_ACCENT_COLOR = "#818cf8"; // indigo-400
export const SLA_MET_COLOR = "#34d399"; // emerald-400
export const SLA_BREACHED_COLOR = "#f87171"; // red-400
```
Consumed by BurnupCard/VelocityCard/ThroughputCard/SlaCard (`SlaCard.tsx:17` adds `CSAT_COLOR #fbbf24`). The app's accent has been periwinkle `#6f6ce0` since the Dusk wave — these charts still draw the retired indigo, and none of the five invert for light mode (emerald-400 `#34d399` as a line on white is ~1.9:1). Fix: SVG `fill`/`stroke` accept CSS variables — point these at `var(--accent-fill)` / `var(--chart-*)`.

**High — chart grid/axis hexes are the *stock* zinc values, not the app's remapped ramp.**
`web/src/components/charts/chart-utils.ts:22-24`
```ts
export const CHART_GRID = "#3f3f46"; // zinc-700
export const CHART_AXIS_TEXT = "#a1a1aa"; // zinc-400
```
Doubly wrong: the comments cite Tailwind's original zinc, but the app's zinc-700 is `#333a46` (index.css:240) — so even in dark mode the charts use a ramp the rest of the UI abandoned; and in light mode they keep dark-tuned greys. Fix: `var(--color-strong)`, `var(--color-fg-secondary)`, `var(--color-fg-muted)`.

**Medium — roadmap connector colors, same class.**
`web/src/components/roadmap/Connectors.tsx:17-23` — `#f87171`, `#71717a` ("zinc-500"), `#fbbf24`, and `#818cf8` annotated *"indigo-400 — the app's interaction accent"* — a stale claim; the accent is `#6f6ce0`. Theme-blind SVG strokes. Same fix as charts.

**Medium — cycle status pills use shades absent from the light remap.**
`web/src/lib/meta.ts:311-317` — `text-blue-200` / `bg-blue-400` / `border-blue-400/30` and `text-emerald-200`: blue-200/400 and emerald-200 are not in the index.css light table, so the Upcoming pill's text renders stock blue-200 on white (~1.4:1 — effectively invisible). Also `components/cycles/CycleBadges.tsx:39` (`text-emerald-200`), `routes/portal-form.tsx:157` / `routes/form-submit.tsx:148` (`text-emerald-200`/`emerald-100` on public, light-capable pages).

**Medium — kind/priority icon colors outside the remap.**
`web/src/lib/meta.ts:84` `text-orange-400` (High priority), `:161` `text-purple-400` (Epic), `:162` `text-blue-400` (Issue). None remapped → pale pastel icons on white (~2.2:1). These icons appear on every card and list row. Either add the shades to the light table or move to remapped 300-shades/tokens.

**Medium — `!bg-amber-950/30` on the internal-note composer.**
`web/src/components/items/CommentsThread.tsx:379` — amber-950 has no light remap: in light theme the internal-note editor gets a near-black brown wash behind dark text. The `!important` prefixes are a second smell (fighting the editor's own surface class instead of parameterizing it).

**Low — hardcoded white fallback.** `web/src/components/items/ValueChip.tsx:6` — `if (!m) return "#fff";` — invisible-ink chip text in light mode when the map misses. Use a token var.

**Low — `rich-editor.css` is no longer "semantic tokens throughout".**
`web/src/components/editor/rich-editor.css:122,126` — `rgba(99, 102, 241, 0.15) /* indigo wash */` and `rgba(14, 165, 233, 0.15) /* sky wash */` behind mention/issue chips. CLAUDE.md states RADD-754 removed this file's raw-color exception; these two literals (one of them literally indigo) contradict it. Use `color-mix` over `var(--accent-fill)` / the sky token.

**Low — `text-black` on `bg-accent` disagrees with the kit.**
`web/src/components/requests/ListSection.tsx:46` — badge is black-on-periwinkle while `Button` primary is white-on-periwinkle (`Button.tsx:26`). Both sit near 4.5:1; pick one and encode it as an on-accent token (the plugin SDK already names `--radd-accent-fg`).

**Legitimate (verified, not violations):** `text-black` on roadmap bars (`BarRow.tsx:173-176`, documented exception); `routes/page-print.css` hexes (print is deliberately unthemed); `SsoButtons.tsx` Google brand marks; `RaddMark.tsx` brand gradient; avatar/label/issue-type color palettes in `routes/settings/profile.tsx:39`, `labels.tsx:17`, `issue-types.tsx:17`, `states.tsx:393` (user-picked *data* colors); `lib/markdown.tsx:257` sky-300 chip (remapped shade).

## 2. Kit bypasses

**Clean:** zero native `<select>` (the one grep hit is a comment), zero `window.confirm`/`alert`/`prompt` — every confirmation goes through `useConfirm` (21 call sites). No native `<dialog>`.

**Medium — 46 hand-rolled `Button variant="secondary" size="sm"` lookalikes.** The `rounded border border-strong px-… text-…` pattern is re-typed across at least 19 files, each with drifting paddings/hovers: `routes/settings/releases.tsx:157`, `routes/settings/users.tsx:304,332`, `routes/settings/cycles.tsx:305,377`, `routes/cycle.tsx:139`, `routes/pages-index.tsx:38`, `routes/public-pages.tsx:39`, `routes/timesheet.tsx:211`, `components/views/DisplayMenu.tsx:67,93`, `components/items/{ItemPagesSection.tsx:111, RelatedLinksSection.tsx:123, AttachmentsSection.tsx:69, TimeTrackingPanel.tsx:232, VcsPanel.tsx:171}`, `components/pages/PageLinkedItems.tsx:106`, `components/automations/ActionsBuilder.tsx:264`, `components/views/carddesigner/PresetPicker.tsx:119`. CLAUDE.md bans hand-rolled action buttons; these are exactly that. Several differ from `Button` only in height.

**Medium — 34 copies of one icon-button class string.** `rounded p-1 text-fg-faint hover:bg-elevated hover:text-red-400 cursor-pointer disabled:opacity-50` appears verbatim in `TimeTrackingPanel.tsx:430`, `SpaceAccessPanel.tsx:99`, `DependenciesSection.tsx:96`, `RelatedLinksSection.tsx:81`, `storage/RuleDialog.tsx:188,262`, `ConditionsBuilder.tsx:136`, `PresetPicker.tsx:90`, `DisplayMenu.tsx:235` and ~25 more. There is no `IconButton` in the kit — this string *is* the de-facto component, maintained by copy-paste.

**Medium — hand-rolled inline confirm.** `web/src/routes/settings/releases.tsx:131-149` — a `confirming` state with bespoke Delete/Cancel buttons where every sibling page uses `useConfirm`. Inconsistent destructive-action UX.

**Low — hand-rolled dropdown/popover shells beside the kit.** `DisplayMenu.tsx:76`, `WipLimitMenu.tsx:70`, `BreadcrumbCrumb.tsx:53`, `settings/SubjectPicker.tsx:69-95` each rebuild the fixed-inset-backdrop + absolute-panel pattern (12 such backdrops total; the editor's are arguably justified by ProseMirror anchoring). `DropdownMenu`/`ContextMenu` exist; the recurring "custom content in a click-away popover" case has no kit primitive, so each author rebuilds it.

**Info — the kit itself is off-token.** `Button.tsx:29-30` danger variants use raw `bg-red-500/90`/`text-red-400`; `TextField.tsx:28`, `Select.tsx:279`, `TokenMultiSelect.tsx:150` use raw `red-500/400` for error states. Consistent with the status-color mechanism, but it means the *kit* hardcodes what should be `--color-danger-*` (see Systemic fixes).

## 3. React hazards

**Medium — `key={index}` on removable, editable rows.** Deleting row N re-keys every row below it; with rows full of inputs/Selects this loses focus and can flash stale editor state:
- `web/src/components/automations/ConditionsBuilder.tsx:145,155` — `key={index}` on `GroupEditor`/`ConditionRow` with `onRemove={() => removeChild(index)}` (verified removable, recursive groups compound it).
- `web/src/components/automations/ActionsBuilder.tsx:204` — same builder pattern.
- `web/src/components/settings/storage/RuleDialog.tsx:155,226` — LLM answer rows, removable.
- `web/src/components/views/ViewSharingEditor.tsx:103`, `components/settings/signin/StartingAccess.tsx:57`, `components/views/ViewModal.tsx:351`.
- `web/src/components/settings/TransitionsSection.tsx:580` — composite `${index}:${choiceId(params)}` partially mitigates; still index-anchored.
Fix: give rows a stable local id at creation (`crypto.randomUUID()` in the add handler) — one shared `useKeyedRows` helper would cover all eight.

**Info — index keys that are fine as-is** (static or append-only render lists): chart elements (`BarChart.tsx:73`, `LineChart.tsx:70`, `StackedBarChart.tsx:70`), separators (`DropdownMenu.tsx:147`, `ContextMenu.tsx:105`), skeletons (`TableSkeleton.tsx:11`), diff rows (`PageVersionDiff.tsx:73`), `PageBody.tsx:88`, `TableNodeView.tsx:98-130`.

**Info — `exhaustive-deps` suppressions: 8, all annotated, none buggy on inspection.** Spot-checked five: `RichEditor.tsx:695` (editor recreate on mode/AI-gate only — deliberate remount-to-reseed), `NewItemModal.tsx:126` ("react to type changes only; user edits stick"), `RoadmapTimeline.tsx:288` (layout-effect domain-shift correction), `PlainEditor.tsx:124` (ref-publish effect), `useBarDrag.ts:341` (RAF loop keyed on `started`). These are the classic "effect event" shape — React 19's `useEffectEvent` would let most drop the suppression — but each carries a correct written justification. Not violations.

**Verified good:** no `value=`/`defaultValue` mixes; large-list hygiene is real — lists/boards page classically behind `Pager` (`routes/view.tsx:333-373`), roadmaps stream in capped bursts (`ROADMAP_MAX_AUTO_PAGES`, view.tsx:374-387) so the 503k-item dataset can never be pulled into one render; page-scoped batch queries (SLA/rollup/timelog) are capped and chunked.

## 4. Data fetching (representative)

Hygiene is strong: one typed wrapper (`lib/api.ts`) with `ApiError`, 401-redirect and a global 403 toast; TanStack Query everywhere; `useDebounced` + query-key-scoped requests make search-as-you-type races structurally impossible (`CommandPalette.tsx:113-133`, `lib/hooks.ts:345-396`); `keepPreviousData` where flicker matters (`lib/queries/users.ts:81,132`).

- **Low** — `web/src/routes/settings/backups.tsx:402`: raw `fetch` with a hand-built `/api/v1` path inside a route component (the other two raw fetches — `lib/sse.ts:55` streaming, `lib/attachments.ts:25` FormData — are justified infrastructure). Move beside `lib/attachments.ts`.
- **Info** — swallowed rejections are rare and deliberate: `RoadmapSurface.tsx:344` (`.catch(() => undefined)` on an optional duration-enrichment batch), `lib/sse.ts:93` (reader cancel). Everything else routes errors to `pushToast`/`isError` UI.

## 5. Accessibility (representative)

Baseline is unusually good — a heuristic sweep for unlabeled icon-only buttons produced 20 candidates and inspection cleared nearly all (real labels via `aria-label`, `aria-expanded`, or text content).

- **Medium** — `Modal` claims `aria-modal="true"` but implements no focus trap (`web/src/components/Modal.tsx:19-75`): it focuses the first control, then Tab walks out into the inert background. Escape/overlay-click are handled (dismiss-stack). One `useFocusTrap` in Modal fixes every dialog at once.
- **Medium** — `web/src/components/settings/SubjectPicker.tsx:69-95`: suggestion list is `onMouseDown`-only — no `onKeyDown` on the input, no `onClick` on the rows, no `role=listbox/option` — so keyboard users cannot grant access to anyone. The kit's `TokenMultiSelect` already implements the correct combobox pattern; this predates/bypasses it.
- **Low** — whole-row `opacity-60` on read notifications (`components/notifications/NotificationRow.tsx:76`) dims `text-fg-muted` content well under 4.5:1 — CLAUDE.md's own "dim is not the same as quiet" rule. Same pattern: `PageInlineComments.tsx:262` (`opacity-70`), `PageVersionDiff.tsx:105`.
- **Low** — `web/src/components/views/carddesigner/CardPreview.tsx:217`: bare `<div onClick={() => onSelect(null)}>` deselect surface, no role/keyboard path (mitigated by the designer's documented keyboard fallback, but the div itself is a click-only control).

## 6. Duplication (representative)

- **Medium** — `web/src/routes/form-submit.tsx` (283 lines) vs `routes/portal-form.tsx` (252): ~150 identical lines including the same success panel and the same non-remapped `text-emerald-200` link. One shared form-renderer with a token/portal wrapper each.
- **Medium** — the "directory" sky chip is hand-copied 4 times: `components/settings/UserSourceBadge.tsx:13`, `TeamPanel.tsx:176`, `DirectoryGroupsSection.tsx:127`, `TeamDirectoryGroup.tsx:66`.
- **Medium** — 109 occurrences of `<p className="text-xs text-red-400">{errorMessage(…)}</p>` (plus size variants). One `<ErrorText error={…}/>` deletes them and gives the danger color a single home.
- **Low** — date formatting: `lib/dates.ts` exists (`shortDate`/`formatDate`/`relativeTime`…) yet 13+ sites call `new Date(x).toLocaleDateString()/toLocaleString()` directly (`routes/projects-index.tsx:71`, `settings/teams.tsx:58`, `settings/users.tsx:290`, `settings/backups.tsx:45`, `settings/audit.tsx:109`, `settings/groups.tsx:73`, `page-print.tsx:93`…), and `lib/timesheet.ts:88-94` grows its own formatters.
- **Low** — the amber warning panel (`border-amber-500/40 bg-amber-500/5 …`) is copied 9 times (`DeleteUserDialog.tsx:109,150`, `MissingPluginType.tsx:22`, …) — a `<Callout kind="warning">` exists conceptually (the editor has callout tokens) but not as a kit component.

## 7. Type safety (representative)

Near-perfect: **zero** `@ts-ignore`/`@ts-expect-error`/`@ts-nocheck`; one `as any` at `web/src/lib/markdown.tsx:41` (unified/mdast visitor, lint-acknowledged); one `as unknown as` at `components/editor/extension-node.ts:111` (mdast node bridge). Both are genuine library-boundary casts. Nothing to fix.

## 8. Dead CSS (cheap greps)

- **Low** — `--color-zinc-300` and `--color-zinc-50` are defined in both theme blocks (`index.css:244,247,332-333`) but referenced by nothing — no semantic alias uses them and web/src has zero zinc utilities. Two dead lines per theme.
- **Low** — `routes/page-print.css:120` still targets `.milkdown-code-block`, a Crepe-era class the RADD-745 editor no longer emits (the node view renders `radd-code-block`, and `web/scripts/code-block-proof.mjs` asserts zero `.milkdown-code-block` nodes). The adjacent `.cm-editor` selector is what actually works; the stale one should be replaced with `.radd-code-block` so the *wrapper* (header chrome included) gets `break-inside: avoid`.
- All 11 custom classes in `editor.css`/`rich-editor.css` are referenced; no other dead rules found.

## File-size rule

64 files exceed ~300 lines. Top: `routes/view.tsx` 1323, `settings/TransitionsSection.tsx` 1031, `editor/RichEditor.tsx` 924, `roadmap/RoadmapSurface.tsx` 922, `router.tsx` 777, `roadmap/RoadmapTimeline.tsx` 686, `routes/timesheet.tsx` 684, `settings/cycles.tsx` 653, `lib/meta.ts` 629, `IssueProperties.tsx` 619. `view.tsx` is 4x the limit and is where most cross-cutting state (paging, quick filters, batches, WIP limits, display) accretes — the natural split is one hook per concern (`useViewPaging`, `useViewBatches`, …), which its section comments already delineate.

---

## Systemic fixes

1. **Introduce a semantic status tier and make the chart layer consume tokens.** The root cause behind most of section 1 is that "danger/warning/success" and the workflow palette exist only as (a) raw utilities filtered through a shade-by-shade light remap and (b) loose hex constants. Add `--color-danger/-warning/-success` (+ `-ink`/`-fill` like the callout scale) in `index.css`, point `Button.danger`, `TextField`/`Select`/`TokenMultiSelect` error states and the new `<ErrorText>`/`<Callout>` at them, and replace every chart/SVG hex constant (`lib/meta.ts:401-409`, `charts/chart-utils.ts:22-24`, `roadmap/Connectors.tsx:17-23`, `SlaCard.tsx:17`, `IssueProperties.tsx:22-35`) with `var(--chart-*)`/`var(--accent-fill)` — SVG accepts CSS variables, so this also makes every chart theme-correct for free. Then a raw palette utility or hex anywhere in `web/src` becomes a review finding with no exceptions to memorize, and the "shade missing from the light remap" bug class (blue-200, orange-400, purple-400, amber-950…) dies with the remap table.
2. **Grow the kit by three components and delete the copies:** `IconButton` (kills the 34-copy class string), `ErrorText` (kills 109 copies), `Callout`/`WarningPanel` (kills 9). Add a `Popover` primitive (backdrop + positioning + dismiss-stack) so `DisplayMenu`/`WipLimitMenu`/`BreadcrumbCrumb`/`SubjectPicker` stop rebuilding it — and rebuild `SubjectPicker` on `TokenMultiSelect`'s combobox mechanics to fix its keyboard dead-end at the same time. Fold the 46 bordered lookalikes into `Button` (`secondary`, `size="sm"`, maybe a new `size="xs"` — most differ from the kit only in height).
3. **One `useKeyedRows` helper for editable row-builders** (id minted at add-time, stable through removal) applied to the eight `key={index}` builders — a one-file fix for the whole hazard class.
4. **Add `useFocusTrap` inside `Modal`** — one change covers every dialog in the app, closing the `aria-modal` gap.
5. **A CI-able style check, in the spirit of the existing zero-zinc rule:** extend the review greps to (a) hex/rgb literals in `.tsx` outside an allowlist (brand marks, data-color palettes), and (b) palette shades not present in the `index.css` light remap. Both are single `rg` invocations and would have caught 8 of the 10 section-1 findings at commit time.
