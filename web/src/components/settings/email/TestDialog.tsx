import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "../../../lib/api";
import { apiMailSenderTestPath } from "../../../lib/constants";
import type { MailSender, MailTestResult } from "../../../lib/types";
import { Button } from "../../Button";
import { ErrorText } from "../../ErrorText";
import { Modal } from "../../Modal";
import { TextField } from "../../TextField";

/**
 * Send one real message and report what happened (RADD-955/958).
 *
 * The Message-ID shown is the one the RELAY reported using — the value
 * threading actually depends on, and not always the one Radd composed.
 */
export function TestDialog({ sender, onClose }: { sender: MailSender; onClose: () => void }) {
  const [to, setTo] = useState("");
  const send = useMutation({
    mutationFn: () =>
      api.post<MailTestResult>(apiMailSenderTestPath(sender.id), { to_address: to }),
  });

  return (
    <Modal title={`Send a test through ${sender.name}`} onClose={onClose}>
      <div className="flex flex-col gap-3">
        <TextField
          label="Send to"
          value={to}
          onChange={(e) => setTo(e.target.value)}
          placeholder="you@example.com"
        />
        {send.data?.ok && (
          <div className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-[13px] text-fg">
            Sent. The relay used Message-ID{" "}
            <code className="font-mono text-[11px]">{send.data.message_id}</code> — that is the
            value replies thread against.
          </div>
        )}
        {send.data && !send.data.ok && (
          <div className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-[12px] text-fg">
            {send.data.error}
          </div>
        )}
        {send.isError && <ErrorText error={send.error} />}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Close
          </Button>
          <Button onClick={() => send.mutate()} disabled={send.isPending || !to.includes("@")}>
            {send.isPending ? "Sending…" : "Send test"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
