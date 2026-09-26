import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, Button, ErrorText, Modal, TextField } from "@radd/plugin-sdk";
import { MailPath } from "./api";
import {
  MailRuleStatus,
  type MailRuleStatusValue,
  type MailSource,
  type RoutingPreviewResult,
} from "./types";

/** Per-status chrome for the rule trace; errored is loudest — the destination line cannot express it. */
const STATUS_STYLE: Record<MailRuleStatusValue, { label: string; text: string }> = {
  [MailRuleStatus.matched]: { label: "matched", text: "text-accent-text-strong" },
  [MailRuleStatus.declined]: { label: "no match", text: "text-fg-muted" },
  [MailRuleStatus.errored]: { label: "failed", text: "text-status-danger-ink" },
  // RADD-994. Deliberately the same muted ink as `no match`: all three mean "did
  // not decide this message", and the WORD is the distinction. Reaching for a
  // fainter tier to make them quieter would put 11px text under 4.5:1, which is
  // the trade this codebase has already refused once.
  [MailRuleStatus.disabled]: { label: "off", text: "text-fg-muted" },
  [MailRuleStatus.not_reached]: { label: "not reached", text: "text-fg-muted" },
};

/**
 * The routing dry run: where would this message land, and which rule decided? The trace is the
 * WHOLE chain in order — disabled, not-reached and failed rules included — because a crashed rule
 * and a declining one otherwise lead to the same destination, and "why didn't my rule fire" is the question.
 */
export function PreviewDialog({
  source,
  onClose,
}: {
  source: MailSource;
  onClose: () => void;
}) {
  const [form, setForm] = useState({
    recipient: source.address,
    sender: "",
    subject: "",
    body: "",
  });
  const run = useMutation({
    mutationFn: () =>
      api.post<RoutingPreviewResult>(MailPath.sourcePreview(source.id), form),
  });

  return (
    <Modal title="Where would this land?" onClose={onClose}>
      <div className="flex flex-col gap-3">
        <p className="text-[11px] text-fg-muted">
          Runs the chain against a made-up message. Nothing is sent and no ticket is created.
        </p>
        <TextField
          label="Delivered to"
          value={form.recipient}
          onChange={(e) => setForm((f) => ({ ...f, recipient: e.target.value }))}
        />
        <TextField
          label="From"
          value={form.sender}
          onChange={(e) => setForm((f) => ({ ...f, sender: e.target.value }))}
        />
        <TextField
          label="Subject"
          value={form.subject}
          onChange={(e) => setForm((f) => ({ ...f, subject: e.target.value }))}
        />
        <TextField
          label="Body"
          value={form.body}
          onChange={(e) => setForm((f) => ({ ...f, body: e.target.value }))}
        />
        {run.data && <PreviewResult result={run.data} />}
        {run.isError && <ErrorText error={run.error} />}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Close
          </Button>
          <Button onClick={() => run.mutate()} disabled={run.isPending}>
            {run.isPending ? "Checking…" : "Check"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

/** The verdict: what the chain decided, what each rule did, and — loudest — what
 * broke on the way. */
function PreviewResult({ result }: { result: RoutingPreviewResult }) {
  const outcomes = result.outcomes ?? [];
  const crashed = outcomes.filter((o) => o.status === MailRuleStatus.errored);

  return (
    <div className="flex flex-col gap-2">
      {crashed.length > 0 && (
        // RADD-993: the `--callout-danger-*` scale, whose ink is TUNED to its
        // own fill (4.51:1 light, 4.56:1 dark). The raw `text-red-400` on
        // `bg-red-500/10` it replaces was a tint the light remap only half
        // reached, and the loudest thing on the panel was the least legible.
        <div className="rounded-md border border-callout-danger-border/60 bg-callout-danger-fill px-3 py-2 text-[13px]">
          <span className="font-medium text-callout-danger-ink">
            {crashed.length === 1
              ? "1 rule failed and was skipped"
              : `${crashed.length} rules failed and were skipped`}
          </span>
          <span className="mt-0.5 block text-[11px] text-fg-secondary">
            The chain kept going so no message would be lost, but the destination below is
            what happens WITH those rules broken — not what they were written to do.
          </span>
        </div>
      )}
      <div className="rounded-md border border-subtle bg-surface/60 px-3 py-2 text-[13px]">
        <span className="text-fg">
          Opens in <strong>{result.project_key || "nowhere — no default set"}</strong>
        </span>
        <span className="mt-0.5 block text-[11px] text-fg-faint">{result.reason}</span>
      </div>
      {outcomes.length > 0 && (
        <div className="flex flex-col gap-1">
          <span className="text-[11px] font-medium uppercase tracking-wide text-fg-muted">
            The chain, top to bottom
          </span>
          {outcomes.map((outcome, index) => {
            const style = STATUS_STYLE[outcome.status];
            return (
              // `data-rule-status` is the proof's handle: the labels are prose and
              // will be reworded, the statuses are the wire contract.
              <div
                key={outcome.rule_id ?? index}
                data-rule-status={outcome.status}
                className="flex flex-col gap-0.5 rounded-md border border-subtle bg-surface/40 px-2 py-1.5"
              >
                <div className="flex items-baseline gap-2 text-[12px]">
                  <span className="w-4 shrink-0 text-center font-mono text-[11px] text-fg-faint">
                    {index + 1}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-fg-secondary">
                    {outcome.rule_name || "(unnamed rule)"}
                  </span>
                  <span className={`shrink-0 font-medium ${style?.text ?? "text-fg-muted"}`}>
                    {style?.label ?? outcome.status}
                  </span>
                </div>
                {outcome.detail && (
                  // Wrapped, never truncated: the detail is the most informative field on the panel.
                  <p className="pl-6 text-[11px] leading-snug break-words text-fg-faint">
                    {outcome.detail}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
