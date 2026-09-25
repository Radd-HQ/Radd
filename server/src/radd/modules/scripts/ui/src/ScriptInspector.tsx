import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, Button, CodeEditor, TextField, TokenList, tokens } from "@radd/plugin-sdk";

import type { ScriptRunOutcome } from "./types";

type Params = Record<string, unknown>;

const note = { fontSize: 12, color: tokens.textMuted, margin: 0 } as const;
const heading = {
  fontSize: 11, fontWeight: 500, letterSpacing: "0.04em", textTransform: "uppercase", color: tokens.textMuted,
} as const;
const pre = {
  maxHeight: 160, overflow: "auto", border: `1px solid ${tokens.border}`, borderRadius: 6, padding: 8,
  background: tokens.bg, color: tokens.text, fontSize: 11, margin: 0,
} as const;

/** `script.run` (outputs) / `script.decide` (ports): the Python body, what it
 *  returns, a timeout, and a Test box that runs it against an issue. */
export function ScriptInspector({
  params,
  onChange,
  decide,
}: {
  params: Params;
  onChange: (params: Params) => void;
  decide: boolean;
}) {
  const listKey = decide ? "ports" : "outputs";
  const [seed, setSeed] = useState("");
  const test = useMutation({
    mutationFn: () =>
      api.post<ScriptRunOutcome>("/scripts/run", {
        body: String(params.body ?? ""),
        item_key: seed.trim(),
        params: Object.fromEntries(
          Object.entries(params).filter(([key]) => !["body", "timeout", "outputs", "ports", "arity", "act_as"].includes(key)),
        ),
        timeout: Math.min(Number(params.timeout) || 60, 120),
      }),
  });
  const outcome = test.data;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }} data-script-node>
      <span style={heading}>Script</span>
      <CodeEditor
        language="python"
        value={String(params.body ?? "")}
        onChange={(body) => onChange({ ...params, body })}
        minHeight={220}
      />
      <span style={heading}>{decide ? "Ports the script may name" : "Outputs the script returns"}</span>
      <TokenList
        value={(params[listKey] as string[]) ?? []}
        onChange={(next) => onChange({ ...params, [listKey]: next })}
        placeholder={decide ? "Add a port…" : "Add an output…"}
        ariaLabel={decide ? "Ports" : "Outputs"}
      />
      <p style={note}>
        {decide
          ? "main(ctx) returns one of these names; anything else — or a failure — takes the unavailable port."
          : "main(ctx) returns a dict; each declared key becomes a token downstream, {{name.key}}."}{" "}
        It runs out of process, in the interpreter from Settings → Scripts, as this automation&rsquo;s identity.
      </p>
      <TextField
        label="Timeout (seconds)"
        type="number"
        min={1}
        max={600}
        value={String(params.timeout ?? 60)}
        onChange={(event) => onChange({ ...params, timeout: Number(event.target.value) || 60 })}
      />
      <div data-script-test style={{ display: "flex", flexDirection: "column", gap: 8, border: `1px solid ${tokens.border}`, borderRadius: 6, padding: 8 }}>
        <TextField
          label="Test with issue"
          value={seed}
          onChange={(event) => setSeed(event.target.value)}
          placeholder="TD-42 (optional)"
        />
        <div>
          <Button small disabled={test.isPending || !String(params.body ?? "").trim()} onClick={() => test.mutate()}>
            {test.isPending ? "Running…" : "Test"}
          </Button>
        </div>
        {test.isError && <span style={{ fontSize: 11, color: tokens.danger }}>{String((test.error as Error).message)}</span>}
        {outcome && (
          <div data-script-outcome={outcome.ok ? "ok" : "failed"} style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 11 }}>
            <span style={{ color: outcome.ok ? tokens.success : tokens.danger }}>
              {outcome.ok ? "ok" : "failed"} · {outcome.duration_ms} ms {outcome.error ? `· ${outcome.error}` : ""}
            </span>
            {outcome.ok && <pre style={pre}>{JSON.stringify(outcome.result, null, 2)}</pre>}
            {outcome.stderr && <pre style={pre}>{outcome.stderr}</pre>}
          </div>
        )}
      </div>
    </div>
  );
}
