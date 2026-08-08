import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "../../../lib/api";
import { apiMailSourcePreviewPath } from "../../../lib/constants";
import {
  MailRuleStatus,
  type MailRuleStatusValue,
  type MailSource,
  type RoutingPreviewResult,
} from "../../../lib/types";
import { Button } from "../../Button";
import { ErrorText } from "../../ErrorText";
import { Modal } from "../../Modal";
import { TextField } from "../../TextField";

/** Per-status chrome for the rule trace. Errored is deliberately the loudest
 * thing on the panel: it is the outcome the destination line cannot express. */
const STATUS_STYLE: Record<MailRuleStatusValue, { label: string; text: string }> = {
  [MailRuleStatus.matched]: { label: "matched", text: "text-accent-text-strong" },
  [MailRuleStatus.declined]: { label: "no match", text: "text-fg-muted" },
  [MailRuleStatus.errored]: { label: "failed", text: "text-red-400" },
};

/**
 * The routing dry run (RADD-958): where would a message like this land, and
 * which rule decided? Settings → Storage paid for this lesson first — an
 * ordered chain nobody can dry-run makes "why did this land there"
 * unanswerable.
 *
 * RADD-989 added the per-rule trace. Reporting only the destination made a
 * CRASHED rule indistinguishable from one that declined — both read as "no rule
 * matched — source default" — which is how every AI mail rule stayed broken for
 * a release. A rule that raised is now called out above the destination, because
 * a destination computed from a chain that partly failed is not an answer.
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
      api.post<RoutingPreviewResult>(apiMailSourcePreviewPath(source.id), form),
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
        <div className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-[13px]">
          <span className="font-medium text-red-400">
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
            Rules consulted
          </span>
          {outcomes.map((outcome, index) => {
            const style = STATUS_STYLE[outcome.status];
            return (
              <div
                key={outcome.rule_id ?? index}
                className="flex items-baseline gap-2 text-[12px]"
              >
                <span className="min-w-0 flex-1 truncate text-fg-secondary">
                  {outcome.rule_name || "(unnamed rule)"}
                </span>
                <span className={`shrink-0 font-medium ${style?.text ?? "text-fg-muted"}`}>
                  {style?.label ?? outcome.status}
                </span>
                {outcome.detail && (
                  <span className="min-w-0 flex-[2] truncate text-[11px] text-fg-faint">
                    {outcome.detail}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
