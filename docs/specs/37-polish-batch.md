# Spec 37 — Polish batch: comment edit/delete, Cmd+Enter, palette actions, recently viewed

Small discussed tidy-ups, one wave:

- **Comment edit/delete in the UI** — the API supported both since spec 02; rows now
  show hover actions (edit for the author, delete for author or project admin,
  two-step confirm), inline markdown edit form, an "(edited)" marker.
- **Cmd/Ctrl+Enter submits** the comment composer and saves an inline comment edit
  (`MarkdownEditor.onSubmitShortcut`).
- **Palette quick actions** — Cmd-K gains an Actions section: "New issue in
  <PROJECT>" for every project where the caller holds `item.create`; choosing one
  opens the New-item modal.
- **My Work "Recently viewed"** — the item detail (page + peek) records a
  per-browser localStorage trail (`lib/recent.ts`, 12 entries); the dashboard shows
  the last 8 as chips that open the peek panel.

Known simplifications: recently-viewed is per-browser (not synced); palette actions
don't yet include context-aware verbs (assign-to-me / set-state on the open issue).
