import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RotateCcw } from "lucide-react";
import { api } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import { SETTING_CHOICE_LABELS } from "../../lib/meta";
import { scopedSettingsQuery } from "../../lib/queries";
import {
  SettingScope,
  inSection,
  withoutSections,
  type ScopedSetting,
  type SettingScopeValue,
} from "../../lib/types";
import { Button } from "../Button";
import { SelectField } from "../SelectField";
import { Spinner } from "../Spinner";
import { QueryError } from "../QueryError";
import { ErrorText } from "../ErrorText";

interface Props {
  scope: SettingScopeValue;
  /** Omit for instance scope; the project id otherwise. */
  scopeId?: string;
  /**
   * Which rows this surface owns (RADD-930) — the `section` the owning plugin
   * declared, matching that section and anything under it. Pass `homed`
   * instead on a General page.
   *
   * This replaces the hand-maintained key arrays each surface used to carry
   * (`DIRECTORY_CONNECTION_KEYS`, `AI_FEATURE_SETTING_KEYS`, …): those had to be
   * edited in two repos' worth of places whenever a plugin added a key, and a
   * key nobody remembered to list silently landed on General.
   */
  section?: string;
  /** General pages only: the section roots that DO have a surface at this
   * scope. Everything else — no section, or a section with no home here — is
   * rendered, so a setting can never fall through the cracks. */
  homed?: readonly string[];
  /** Grey out the editors (spec 85: directory keys without a bind account). */
  disabled?: boolean;
  /** Escape hatch for a surface that needs a predicate rather than a section. */
  filter?: (row: ScopedSetting) => boolean;
  /** Shown instead of the default when this surface owns no rows. */
  emptyLabel?: string;
}

/**
 * Editor for the scalar settings that cascade project → instance (specs 50/67).
 * Reusable at either scope: shows each setting's effective value and whether it's
 * overridden here (vs inherited); a change writes the override, Reset clears it.
 */
export function ScopedSettingsEditor({
  scope,
  scopeId,
  section,
  homed,
  filter,
  disabled,
  emptyLabel,
}: Props) {
  const query = useQuery(scopedSettingsQuery(scope, scopeId));
  if (query.isPending) return <Spinner label="Loading settings…" />;
  if (query.isError) {
    return <QueryError label="settings" error={query.error} />;
  }
  let rows: readonly ScopedSetting[] = query.data;
  if (section !== undefined) rows = inSection(rows, section);
  if (homed !== undefined) rows = withoutSections(rows, homed);
  if (filter) rows = rows.filter(filter);
  if (rows.length === 0) {
    return (
      <p className="text-xs text-fg-muted">
        {emptyLabel ?? "No cascaded settings apply at this scope."}
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      {rows.map((row) => (
        <SettingRow key={row.key} row={row} scope={scope} scopeId={scopeId} disabled={disabled} />
      ))}
    </div>
  );
}

/** RADD-1288: which way a row's last write went, for the inline status. */
type SaveState = "idle" | "saving" | "saved" | "error";

/** The seven day tokens `work_week_days` stores, in display order. */
const WEEK_DAYS = [
  ["mon", "Mon"], ["tue", "Tue"], ["wed", "Wed"], ["thu", "Thu"],
  ["fri", "Fri"], ["sat", "Sat"], ["sun", "Sun"],
] as const;

/**
 * One cascaded setting, AUTOSAVED (RADD-1288, decided 2026-09-23): toggles,
 * choices and day toggles write on change; text writes on blur or Enter and
 * Escape reverts. There is no Save button to hunt for — the row says
 * Saving… / Saved / what went wrong, and Reset returns it to the inherited value.
 */
function SettingRow({
  row,
  scope,
  scopeId,
  disabled,
}: {
  row: ScopedSetting;
  scope: SettingScopeValue;
  scopeId?: string;
  disabled?: boolean;
}) {
  const queryClient = useQueryClient();
  const stored = String(row.value ?? "");
  const [value, setValue] = useState(stored);
  const [editing, setEditing] = useState(false);
  const [state, setState] = useState<SaveState>("idle");
  // Follow the server when nobody is typing here (a reset, another tab, a normalised write).
  useEffect(() => {
    if (!editing) setValue(stored);
  }, [stored, editing]);
  useEffect(() => {
    if (state !== "saved") return;
    const timer = window.setTimeout(() => setState("idle"), 2000);
    return () => window.clearTimeout(timer);
  }, [state]);
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["scoped-settings", scope, scopeId ?? null] });

  const save = useMutation({
    mutationFn: (next: string) =>
      api.put(ApiPath.scopedSettings, { scope, scope_id: scopeId, key: row.key, value: next }),
    onMutate: () => setState("saving"),
    onSuccess: () => setState("saved"),
    onError: () => setState("error"),
    onSettled: invalidate,
  });
  const reset = useMutation({
    mutationFn: () =>
      api.delete(ApiPath.scopedSettings, {
        query: scopeId ? { scope, scope_id: scopeId, key: row.key } : { scope, key: row.key },
      }),
    onMutate: () => setState("saving"),
    onSuccess: () => setState("saved"),
    onError: () => setState("error"),
    onSettled: invalidate,
  });

  const commit = (next: string) => {
    setValue(next);
    if (next !== stored) save.mutate(next);
  };
  const commitText = () => {
    setEditing(false);
    if (value !== stored) save.mutate(value);
  };
  // Project scope inherits from the instance's General defaults; at instance
  // scope an un-overridden value IS the (env/config) default, not "inherited".
  const unsetLabel = scope === SettingScope.instance ? "Default" : "Inherited";
  const busy = disabled || save.isPending || reset.isPending;
  const days = new Set(value.split(",").map((day) => day.trim()).filter(Boolean));

  return (
    <div className="rounded-lg border border-subtle p-3" data-setting={row.key}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[13px] font-medium text-heading">{row.label}</p>
          <p className="text-xs text-fg-muted">{row.description}</p>
        </div>
        <span
          className={
            "shrink-0 rounded px-1.5 py-px text-[10px] " +
            (row.set_here ? "bg-accent/15 text-accent-text" : "text-fg-faint")
          }
        >
          {row.set_here ? "Set here" : unsetLabel}
        </span>
      </div>
      <div className="mt-2 flex items-center gap-2">
        {row.key === "work_week_days" ? (
          <div role="group" aria-label={row.label} className="flex flex-1 flex-wrap gap-1">
            {WEEK_DAYS.map(([day, label]) => {
              const on = days.has(day);
              return (
                <button key={day} type="button" aria-pressed={on} disabled={busy} data-day={day}
                  onClick={() => commit(WEEK_DAYS.map(([d]) => d).filter((d) => (d === day ? !on : days.has(d))).join(","))}
                  className={"h-7 w-11 rounded-md border text-xs font-medium cursor-pointer transition-colors " +
                    "focus-visible:outline-2 focus-visible:outline-focus disabled:opacity-50 " +
                    (on ? "border-accent bg-accent/15 text-accent-text" : "border-subtle text-fg-muted hover:text-fg")}>
                  {label}
                </button>
              );
            })}
          </div>
        ) : row.type === "bool" ? (
          <label className="flex flex-1 items-center gap-2 text-xs text-fg">
            <input
              type="checkbox"
              checked={value === "true"}
              onChange={(event) => commit(event.target.checked ? "true" : "false")}
              disabled={busy}
              className="size-4 accent-accent disabled:opacity-50"
            />
            Enabled
          </label>
        ) : row.choices ? (
          // Enumerated setting: a select over the server's accepted values with
          // friendly labels — never a free-text footgun.
          <div className="flex-1">
            <SelectField
              label=""
              ariaLabel={row.label}
              value={value}
              onChange={(event) => commit(event.target.value)}
              disabled={busy}
            >
              {row.choices.map((choice) => (
                <option key={choice} value={choice}>
                  {SETTING_CHOICE_LABELS[row.key]?.[choice] ?? choice}
                </option>
              ))}
            </SelectField>
          </div>
        ) : (
          <input
            type={row.type === "int" ? "number" : row.secret ? "password" : "text"}
            aria-label={row.label}
            value={value}
            onFocus={() => setEditing(true)}
            onChange={(event) => setValue(event.target.value)}
            onBlur={commitText}
            onKeyDown={(event) => {
              if (event.key === "Enter") event.currentTarget.blur();
              if (event.key === "Escape") {
                setValue(stored);
                setEditing(false);
                event.currentTarget.blur();
              }
            }}
            disabled={disabled}
            className="h-8 flex-1 rounded-md border border-strong bg-surface px-2 text-[13px] text-heading focus:outline-2 focus:outline-focus disabled:opacity-50"
          />
        )}
        <span aria-live="polite" className="w-16 shrink-0 text-[11px] text-fg-muted" data-save-state={state}>
          {state === "saving" ? "Saving…" : state === "saved" ? "Saved" : ""}
        </span>
        {row.set_here && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => reset.mutate()}
            disabled={busy}
            title={`Reset to the inherited value (${String(row.default)})`}
          >
            <RotateCcw size={13} aria-hidden />
            Reset
          </Button>
        )}
      </div>
      {state === "error" && (
        <ErrorText className="mt-1" error={save.error ?? reset.error} />
      )}
    </div>
  );
}
