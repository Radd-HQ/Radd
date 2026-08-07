import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "../../../lib/api";
import { apiMailSourcePreviewPath } from "../../../lib/constants";
import type { MailSource, RoutingPreviewResult } from "../../../lib/types";
import { Button } from "../../Button";
import { ErrorText } from "../../ErrorText";
import { Modal } from "../../Modal";
import { TextField } from "../../TextField";

/**
 * The routing dry run (RADD-958): where would a message like this land, and
 * which rule decided? Settings → Storage paid for this lesson first — an
 * ordered chain nobody can dry-run makes "why did this land there"
 * unanswerable.
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
        {run.data && (
          <div className="rounded-md border border-subtle bg-surface/60 px-3 py-2 text-[13px]">
            <span className="text-fg">
              Opens in <strong>{run.data.project_key || "nowhere — no default set"}</strong>
            </span>
            <span className="mt-0.5 block text-[11px] text-fg-faint">{run.data.reason}</span>
          </div>
        )}
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
