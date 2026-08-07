import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RotateCcw, Save } from "lucide-react";
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
 * Reusable at either scope: shows each setting's effective value, whether it's
 * overridden here (vs inherited), Save writes the override, Reset clears it.
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
  const [value, setValue] = useState(String(row.value ?? ""));
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["scoped-settings", scope, scopeId ?? null] });

  const save = useMutation({
    mutationFn: () =>
      api.put(ApiPath.scopedSettings, { scope, scope_id: scopeId, key: row.key, value }),
    onSuccess: invalidate,
  });
  const reset = useMutation({
    mutationFn: () =>
      api.delete(ApiPath.scopedSettings, {
        query: scopeId ? { scope, scope_id: scopeId, key: row.key } : { scope, key: row.key },
      }),
    onSuccess: invalidate,
  });

  const dirty = value !== String(row.value ?? "");
  // Project scope inherits from the instance's General defaults; at instance
  // scope an un-overridden value IS the (env/config) default, not "inherited".
  const unsetLabel = scope === SettingScope.instance ? "Default" : "Inherited";

  return (
    <div className="rounded-lg border border-subtle p-3">
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
        {row.type === "bool" ? (
          <label className="flex flex-1 items-center gap-2 text-xs text-fg">
            <input
              type="checkbox"
              checked={value === "true"}
              onChange={(event) => setValue(event.target.checked ? "true" : "false")}
              disabled={disabled}
              className="size-4 accent-accent disabled:opacity-50"
            />
            Enabled
          </label>
        ) : row.choices ? (
          // Enumerated setting (spec 107 cleanup): a select over the server's
          // accepted values with friendly labels — never a free-text footgun.
          <div className="flex-1">
            <SelectField
              label=""
              value={value}
              onChange={(event) => setValue(event.target.value)}
              disabled={disabled}
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
            value={value}
            onChange={(event) => setValue(event.target.value)}
            disabled={disabled}
            className="h-8 flex-1 rounded-md border border-strong bg-surface px-2 text-[13px] text-heading focus:outline-2 focus:outline-focus disabled:opacity-50"
          />
        )}
        <Button onClick={() => save.mutate()} disabled={disabled || !dirty || save.isPending}>
          <Save size={13} aria-hidden />
          {save.isPending ? "Saving…" : "Save"}
        </Button>
        {row.set_here && (
          <Button
            variant="ghost"
            onClick={() => reset.mutate()}
            disabled={disabled || reset.isPending}
            title={`Reset to the inherited default (${String(row.default)})`}
          >
            <RotateCcw size={13} aria-hidden />
          </Button>
        )}
      </div>
      {(save.isError || reset.isError) && (
        <ErrorText className="mt-1" error={save.error ?? reset.error} />
      )}
    </div>
  );
}
