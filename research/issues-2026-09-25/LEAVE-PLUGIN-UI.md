# RADD-1342 — Leave settings belong to the plugin

Disabling Leave hid Holidays in Time logging but left Leave in Profile. Both sections were imported directly from the host's `components/settings/LeaveSections.tsx`; only Time logging checked plugin availability. The existing `profile.section` slot was not being used for Leave.

The Leave module now owns a federated UI remote in `server/src/radd/modules/leave/ui`. Its two contributions target `profile.section` and `settings.section` matched to `timelogging`. Profile retains its existing slot; Time logging now provides a generic section slot. Neither settings page imports Leave components or names its enablement key. The remote uses SDK primitives, API and user context, preserves date-only formatting and profile-timezone defaults, and shows load/save/delete errors. Disabling unloads both settings contributions through the existing plugin loader.

The shared avatar/name lookup and timesheet calendar were also fetching Leave unconditionally (or only checking authentication). They now gate requests and suppress retained query data when disabled. Those are still host integrations; this change does not claim a complete migration of all Leave UI to slots.

Verification:

- Build/type-check the host and every plugin remote: `node web/scripts/build-all.mjs`.
- Built-browser regression: `node web/scripts/browser-leave-availability.mjs` loads the actual remote, checks disabled initial requests, live slot withdrawal/restoration, personal leave creation/removal, team holiday submission, and cached avatar/timesheet indicators disappearing on disable.
- Focused backend Leave and module-boundary tests; frontend unit suite.
- Local API probe enables/disables Leave in the same server process, checks its advertised remote and served JavaScript, and restores the user's disabled state. Loading the new manifest code required one development-server restart; subsequent plugin toggles do not.

Results: host plus all 9 remotes built and type-checked; browser regression passed; 11 focused backend tests and 33 frontend unit tests passed. Ruff and diff whitespace checks passed. Local enable/disable succeeded on PID 1931087 and restored Leave to disabled.
