import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Slot, SlotId } from "@radd/plugin-sdk";
import { Bell, Save } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { ApiPath, RoutePath } from "../../lib/constants";
import { AuthStatus } from "../../lib/auth";
import { useAuthState } from "../../lib/hooks";
import { mePreferencesQuery, queryKeys } from "../../lib/queries";
import { type Me, type ProfileUpdate } from "../../lib/types";
import { Avatar } from "../../components/Avatar";
import { EDITOR_AI_PREF_KEY } from "../../components/editor/ai";
import { Density, Theme, setDensity, setTheme, useAppearance } from "../../lib/theme";
import { Button } from "../../components/Button";
import { Select } from "../../components/Select";
import { TextField } from "../../components/TextField";
import { MyLeaveSection } from "../../components/settings/LeaveSections";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { TotpPanel } from "../../components/settings/TotpPanel";
import { ErrorText } from "../../components/ErrorText";
import { browserTimeZone } from "../../lib/dates";

/** Curated avatar palette (any hex works via the color input). */
const AVATAR_COLORS = [
  "#6366f1", "#8b5cf6", "#ec4899", "#ef4444", "#f59e0b",
  "#10b981", "#14b8a6", "#0ea5e9", "#64748b",
] as const;

/** Personal profile (spec 34): avatar, timezone, name. Tokens live on their
 * own Settings page — one home per surface (RADD-1095). */
export function ProfileSettingsPage() {
  const authState = useAuthState();
  const user = authState?.status === AuthStatus.authenticated ? authState.user : null;

  return (
    <SettingsPage
      title="Profile"
      description="How you appear across Radd, and the timezone your timestamps are shown in."
    >
      {user ? (
        <ProfileForm user={user} />
      ) : (
        <p className="text-sm text-fg-muted">Sign in to edit your profile.</p>
      )}

      <AppearanceSection />

      <section className="mt-8 border-t border-subtle pt-6">
        <h2 className="mb-1 text-sm font-semibold text-fg">Leave</h2>
        <p className="mb-4 text-xs text-fg-muted">
          Your absences show on the timesheet and dim your avatar everywhere while you're
          away. Team-wide holidays are defined under Settings → Holidays.
        </p>
        <MyLeaveSection />
      </section>

      <section className="mt-8 border-t border-subtle pt-6">
        <h2 className="mb-1 text-sm font-semibold text-fg">Notifications</h2>
        <p className="mb-3 text-xs text-fg-muted">
          Which events reach your inbox and which also email you — per kind, and per how you
          are connected to the work: your own issues, things you follow, your teams, or a
          whole project, space or team you subscribe to.
        </p>
        <Link
          to={RoutePath.settingsNotifications}
          className="inline-flex items-center gap-1.5 text-[13px] text-accent-text hover:text-accent-text-strong"
        >
          <Bell size={14} aria-hidden />
          Notification settings
        </Link>
      </section>

      <section className="mt-8 border-t border-subtle pt-6">
        <h2 className="mb-1 text-sm font-semibold text-fg">AI assistance</h2>
        <p className="mb-4 text-xs text-fg-muted">
          Personal opt-out for the editor's AI menu. Whether the feature exists at all is an
          instance setting (Settings → AI).
        </p>
        <EditorAiPanel />
      </section>

      <section className="mt-8 border-t border-subtle pt-6">
        <h2 className="mb-1 text-sm font-semibold text-fg">Two-factor authentication</h2>
        <p className="mb-4 text-xs text-fg-muted">
          One-time codes from an authenticator app, required at sign-in. Applies to
          email/password sign-in only — SSO and directory accounts keep their provider's MFA.
        </p>
        <TotpPanel />
      </section>

      {/* Plugin-contributed per-user preferences (spec 94): a plugin adds a Profile section by
          registering a `profile.section` slot — its per-account settings live here. */}
      <Slot id={SlotId.profileSection} />
    </SettingsPage>
  );
}

function ProfileForm({ user }: { user: Me }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(user.name);
  const [color, setColor] = useState(user.avatar_color ?? "");
  const [emoji, setEmoji] = useState(user.avatar_emoji ?? "");
  const [timezone, setTimezone] = useState(user.timezone ?? "");
  const [saved, setSaved] = useState(false);

  // Re-seed drafts if the cached user refreshes underneath us.
  useEffect(() => {
    setName(user.name);
    setColor(user.avatar_color ?? "");
    setEmoji(user.avatar_emoji ?? "");
    setTimezone(user.timezone ?? "");
  }, [user]);

  const save = useMutation({
    mutationFn: (body: ProfileUpdate) => api.patch<Me>(ApiPath.me, body),
    onSuccess: () => {
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
      void queryClient.invalidateQueries({ queryKey: queryKeys.authState });
      // Avatars ride on item/comment reads too — refresh the world lazily.
      void queryClient.invalidateQueries();
    },
  });

  const preview = {
    id: user.id,
    name: name || user.name,
    avatar_color: color || null,
    avatar_emoji: emoji || null,
  };

  const timezones: string[] =
    typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : [];
  const browserZone = browserTimeZone();

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate({
      name: name.trim() || undefined,
      avatar_color: color || null,
      avatar_emoji: emoji.trim() || null,
      timezone,
    });
  };

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-5">
      <div className="flex items-center gap-4">
        <Avatar user={preview} size="lg" />
        <div className="text-xs text-fg-muted">
          <p className="text-sm font-medium text-fg">{user.name}</p>
          <p>{user.email}</p>
          <p className="mt-1">
            Your avatar shows your initials on the chosen color — or an emoji if you set one.
          </p>
        </div>
      </div>

      <div className="grid max-w-xl grid-cols-2 gap-4">
        <TextField
          label="Display name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          maxLength={200}
          required
        />

        <div className="flex flex-col gap-1.5">
          <label htmlFor="avatar-emoji" className="text-xs font-medium text-fg-secondary">
            Avatar emoji (optional)
          </label>
          <input
            id="avatar-emoji"
            value={emoji}
            onChange={(event) => setEmoji(event.target.value)}
            placeholder="🦊"
            maxLength={16}
            className="h-8 rounded-md border border-strong bg-surface px-2.5 text-[13px] text-heading placeholder:text-fg-faint focus:outline-2 focus:outline-offset-1 focus:outline-focus"
          />
        </div>

        <div className="col-span-2 flex flex-col gap-1.5">
          <span className="text-xs font-medium text-fg-secondary">Avatar color</span>
          <div className="flex items-center gap-1.5">
            {AVATAR_COLORS.map((swatch) => (
              <button
                key={swatch}
                type="button"
                onClick={() => setColor(swatch)}
                aria-label={`Use color ${swatch}`}
                style={{ backgroundColor: swatch }}
                className={
                  "size-6 rounded-full cursor-pointer " +
                  (color === swatch ? "ring-2 ring-white/80 ring-offset-2 ring-offset-base" : "")
                }
              />
            ))}
            <input
              type="color"
              value={color || "#6366f1"}
              onChange={(event) => setColor(event.target.value)}
              aria-label="Custom avatar color"
              className="h-6 w-8 cursor-pointer rounded border border-strong bg-surface p-0.5"
            />
            {color && (
              <button
                type="button"
                onClick={() => setColor("")}
                className="text-xs text-fg-muted hover:text-fg cursor-pointer"
              >
                Reset
              </button>
            )}
          </div>
        </div>

        <div className="col-span-2 flex flex-col gap-1.5">
          <label htmlFor="profile-tz" className="text-xs font-medium text-fg-secondary">
            Timezone
          </label>
          <Select
            id="profile-tz"
            value={timezone}
            onChange={setTimezone}
            className="max-w-sm"
            options={[
              { value: "", label: `Browser default (${browserZone})` },
              ...timezones.map((zone) => ({ value: zone, label: zone })),
            ]}
          />
          <p className="text-[11px] text-fg-faint">
            Every time Radd shows you — comments, history, the timesheet's today — is in this
            zone. Dates without a time (due dates, cycles) are calendar days and never shift.
          </p>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <Button type="submit" disabled={save.isPending || !name.trim()}>
          <Save size={14} aria-hidden />
          {save.isPending ? "Saving…" : "Save profile"}
        </Button>
        {saved && <span className="text-xs text-emerald-400">Saved.</span>}
        {save.isError && (
          <span className="text-xs text-red-400">{errorMessage(save.error)}</span>
        )}
      </div>
    </form>
  );
}


/** The editor-AI opt-out (specs 101/103), stored server-side in the preferences
 * dict (spec 94 shallow-merge PUT) so it follows the account across browsers.
 * An absent key means enabled; the key lives with the editor wiring in
 * components/editor/ai.ts, which reads the same gate. */
function EditorAiPanel() {
  const queryClient = useQueryClient();
  const prefs = useQuery(mePreferencesQuery());
  const save = useMutation({
    mutationFn: (enabled: boolean) =>
      api.put<Record<string, unknown>>(ApiPath.mePreferences, { [EDITOR_AI_PREF_KEY]: enabled }),
    onSuccess: (data) => queryClient.setQueryData(queryKeys.mePreferences, data),
  });

  if (prefs.isPending) return <p className="text-xs text-fg-faint">Loading preferences…</p>;
  if (prefs.isError)
    return <p className="text-xs text-red-400">Failed to load: {errorMessage(prefs.error)}</p>;

  const enabled = prefs.data[EDITOR_AI_PREF_KEY] !== false;
  return (
    <div className="flex flex-col gap-2">
      <label className="flex items-center gap-2 text-[13px] text-fg">
        <input
          type="checkbox"
          checked={enabled}
          onChange={() => save.mutate(!enabled)}
          disabled={save.isPending}
          className="size-3.5 accent-accent"
        />
        AI writing actions in the editor
      </label>
      {save.isError && <ErrorText error={save.error} />}
    </div>
  );
}

/** Theme + density (spec 39) — per-browser, applied instantly. */
function AppearanceSection() {
  const { theme, density } = useAppearance();
  return (
    <section className="mt-8 border-t border-subtle pt-6">
      <h2 className="mb-3 text-sm font-semibold text-fg">Appearance</h2>
      <div className="flex flex-wrap items-center gap-6 text-xs text-fg-secondary">
        <div className="flex items-center gap-2">
          Theme
          {([Theme.dark, Theme.light] as const).map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => setTheme(option)}
              className={
                "rounded-md border px-2.5 py-1 capitalize cursor-pointer " +
                (theme === option
                  ? "border-accent-hover/60 bg-accent/10 text-accent-text"
                  : "border-strong text-fg-secondary hover:border-emphasis")
              }
            >
              {option}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          Density
          {([Density.normal, Density.compact] as const).map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => setDensity(option)}
              className={
                "rounded-md border px-2.5 py-1 capitalize cursor-pointer " +
                (density === option
                  ? "border-accent-hover/60 bg-accent/10 text-accent-text"
                  : "border-strong text-fg-secondary hover:border-emphasis")
              }
            >
              {option}
            </button>
          ))}
        </div>
        <span className="text-fg-faint">Per-browser preferences.</span>
      </div>
    </section>
  );
}
