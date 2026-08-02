# Spec 39 — Light theme + density toggle

The dark-only UI was a named adoption blocker. Tailwind v4 utilities compile to
CSS-variable references (`.bg-zinc-950 { background-color: var(--color-zinc-950) }`),
so the theme is a **variable remap under `html.light`** — zero per-component class
changes:

- The zinc scale inverts (950 → near-white page, 900 → white panels, …,
  100 → near-black headings) and the dark-tuned accent TEXT shades (`indigo-300`,
  `amber-300`, `emerald-300/400`, `red-300/400`…) deepen to their light-legible
  equivalents (hardcoded hex — Tailwind only emits variables that utilities use).
- `color-scheme: light` fixes native controls (date pickers, scrollbars).
- **Density**: `html.compact body { zoom: 0.9 }` scales the whole px-sized UI.
- Preferences live per-browser (`lib/theme.ts`, applied before first paint in
  `main.tsx`); toggles in the user menu (quick theme flip) and the Profile page's
  Appearance section (theme + density).

Known simplifications: a first-pass palette inversion — individual surfaces may
want hand-tuning (shadows, the amber internal-comment tint) after real use; no
`prefers-color-scheme` auto mode yet; preferences aren't synced to the profile
(add to `users` when cross-device matters).
