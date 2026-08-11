import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RotateCcw, Save } from "lucide-react";
import { api } from "../../../lib/api";
import { ApiPath } from "../../../lib/constants";
import { scopedSettingsQuery } from "../../../lib/queries";
import { SettingScope, type ScopedSetting } from "../../../lib/types";
import { Button } from "../../Button";
import { ErrorText } from "../../ErrorText";
import { QueryError } from "../../QueryError";
import { Spinner } from "../../Spinner";

/** Mirrors the backend `SettingKey.MAIL_ACK_BODY` — not registered in the
 * client's `SettingKey` map (that one lists only keys with a client-side
 * GATE; this card just reads/writes one row by name, the same way the
 * generic settings editor does). */
const ACK_BODY_KEY = "mail_ack_body";

const ACK_TOKENS = ["{{key}}", "{{title}}", "{{link}}", "{{requester_name}}"];

/**
 * The acknowledgement email's body (RADD-1045) — a scalar cascade setting
 * (`mail_ack_body`, instance-only) since this wave, not the module constant
 * it used to be. A dedicated card rather than a row in the generic
 * `ScopedSettingsEditor`: that editor renders every STRING setting as a
 * single-line `<input>`, and this one is a paragraph of prose with
 * `{{token}}` variables — worth a textarea and the token list underneath it,
 * same shape as the canned-response editor (Settings → Canned responses).
 *
 * Reads/writes through the same generic `/scoped-settings` API every other
 * cascade setting uses — no new endpoint, just a different rendering of one
 * row (RADD-930: `section="email"` is what places that row on THIS page
 * instead of General).
 */
export function AckTemplatePanel() {
  const query = useQuery(scopedSettingsQuery(SettingScope.instance));
  if (query.isPending) return <Spinner label="Loading the ack template…" />;
  if (query.isError) return <QueryError label="the ack template" error={query.error} />;
  const row = query.data.find((setting) => setting.key === ACK_BODY_KEY);
  // Absent when mailintake is disabled (its settings_keys contribution
  // unmounts with the plugin) — nothing to edit, so the card is just gone
  // rather than showing a form that would 404 on save.
  if (!row) return null;
  return <AckTemplateForm row={row} />;
}

function AckTemplateForm({ row }: { row: ScopedSetting }) {
  const queryClient = useQueryClient();
  const [value, setValue] = useState(String(row.value ?? ""));
  const invalidate = () =>
    queryClient.invalidateQueries({
      queryKey: ["scoped-settings", SettingScope.instance, null],
    });

  const save = useMutation({
    mutationFn: () =>
      api.put(ApiPath.scopedSettings, { scope: SettingScope.instance, key: row.key, value }),
    onSuccess: invalidate,
  });
  const reset = useMutation({
    mutationFn: () =>
      api.delete(ApiPath.scopedSettings, {
        query: { scope: SettingScope.instance, key: row.key },
      }),
    onSuccess: () => {
      setValue(String(row.default ?? ""));
      invalidate();
    },
  });

  const dirty = value !== String(row.value ?? "");

  return (
    <section>
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-heading">Acknowledgement email</h3>
          <p className="mt-0.5 text-[11px] text-fg-muted">
            The receipt sent when an email opens a ticket. Plain text — tokens substitute,
            anything else is sent verbatim. Empty sends the default wording.
          </p>
        </div>
        <span
          className={
            "shrink-0 rounded px-1.5 py-px text-[10px] " +
            (row.set_here ? "bg-accent/15 text-accent-text" : "text-fg-faint")
          }
        >
          {row.set_here ? "Set here" : "Default"}
        </span>
      </div>
      <textarea
        value={value}
        onChange={(event) => setValue(event.target.value)}
        rows={5}
        placeholder={String(row.default ?? "")}
        className="w-full rounded-md border border-strong bg-surface px-2.5 py-2 text-[13px] text-heading placeholder:text-fg-faint focus:outline-2 focus:outline-offset-1 focus:outline-focus"
      />
      <p className="mt-1.5 text-[11px] text-fg-muted">
        Tokens:{" "}
        {ACK_TOKENS.map((token, index) => (
          <span key={token}>
            <code className="rounded bg-elevated px-1 py-0.5 text-[11px]">{token}</code>
            {index < ACK_TOKENS.length - 1 ? ", " : ""}
          </span>
        ))}
      </p>
      <div className="mt-2 flex items-center gap-2">
        <Button onClick={() => save.mutate()} disabled={!dirty || save.isPending}>
          <Save size={13} aria-hidden />
          {save.isPending ? "Saving…" : "Save"}
        </Button>
        {row.set_here && (
          <Button variant="ghost" onClick={() => reset.mutate()} disabled={reset.isPending}>
            <RotateCcw size={13} aria-hidden />
            Reset to default
          </Button>
        )}
      </div>
      {(save.isError || reset.isError) && (
        <ErrorText className="mt-1" error={save.error ?? reset.error} />
      )}
    </section>
  );
}
