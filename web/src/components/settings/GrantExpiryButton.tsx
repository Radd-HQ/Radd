import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "../../lib/api";
import { Button } from "../Button";
import { Modal } from "../Modal";
import { TextField } from "../TextField";
import { ErrorText } from "../ErrorText";

export function GrantExpiryButton({ path, onSaved }: { path: string; onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [expires, setExpires] = useState("");
  const save = useMutation({
    mutationFn: () => api.patch(path, { expires_at: expires ? new Date(expires).toISOString() : null }),
    onSuccess: () => { onSaved(); setOpen(false); },
  });
  return <><Button variant="ghost" size="sm" onClick={() => setOpen(true)}>Change expiry…</Button>
    {open && <Modal title="Change grant expiry" onClose={() => setOpen(false)}>
      <form className="space-y-3" onSubmit={e => { e.preventDefault(); save.mutate(); }}>
        <TextField type="datetime-local" label="New expiry" value={expires} onChange={e => setExpires(e.target.value)} hint="Uses your local time. Empty makes this grant permanent." />
        <p className="text-xs text-fg-muted">Extending an expired grant restores the access it grants.</p>
        {save.isError && <ErrorText error={save.error} />}
        <Button type="submit" disabled={save.isPending}>{expires ? "Set expiry" : "Make permanent"}</Button>
      </form>
    </Modal>}
  </>;
}
