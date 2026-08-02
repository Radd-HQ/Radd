# Spec 34 — Personal profile: avatar, timezone, tokens

A self-service profile section: how you appear across Radd, your timezone, and your
personal API tokens in one place.

## Backend (auth module change — no new module)

- `users` gains `avatar_color` (`#rrggbb`, nullable), `avatar_emoji` (nullable),
  `timezone` (IANA name, `""` = browser default).
- **`PATCH /auth/me`** (`ProfileUpdate`: name / avatar_color / avatar_emoji /
  timezone; omitted = unchanged, explicit null clears an avatar field; color
  pattern-validated). Email and roles are NOT editable here (user.manage owns
  those). Emits `user.updated` with `action: profile_updated`.
- `MeRead`/`UserRead` expose the new fields, and **`UserRef` (assignee/reporter/
  comment author embeds) now carries `avatar_color`/`avatar_emoji`** so avatars
  render everywhere without extra fetches.

## Frontend

- **`components/Avatar.tsx`** — the one avatar renderer: chosen emoji, else
  initials on the chosen color, else a stable per-user fallback hue (djb2 over the
  id). Used in comments, My Work rows, and the user menu.
- **`/settings/profile`** (first entry in settings nav; also in the user menu):
  live avatar preview, curated color swatches + free color input + reset, emoji
  override, display-name edit, timezone select (`Intl.supportedValuesOf`), and the
  **API tokens panel** (create/list/revoke — extracted to a shared
  `TokensPanel`, still available at `/settings/tokens`).

## Known simplifications

- Avatar is generated (initials/emoji + color) — no image upload yet (the S3 seam
  from spec 33 makes that easy later).
- `timezone` is stored and returned but not yet applied to server-rendered times
  (digest emails have no timestamps today); client rendering already uses the
  browser zone. It becomes load-bearing with calendar/digest features.
- No self-service password change or email change (admin/user.manage flows own
  identity).
