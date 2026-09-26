import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { api, Button, ErrorText, Modal, TextField, toast, ToastKind, useDebounced } from "@radd/plugin-sdk";
import { ImportReview } from "./ImportReview";
import { ImportResults, pickRowClasses } from "./ImportResults";
import { directoryUsersQuery, refreshAfterImport } from "./queries";
import {
  AffectedKeys,
  ImportResolution,
  LdapPath,
  SEARCH_DEBOUNCE_MS,
  type DirectoryUserImportRequest,
  type DirectoryUserImportResult,
  type ImportCandidate,
  type ImportResolutionEntry,
} from "./types";

/** What each resolution actually did, for the result list (spec 88). */
const RESULT_LABELS: Record<string, string> = {
  [ImportResolution.create]: "provisioned",
  [ImportResolution.overwrite]: "existing account re-addressed to AD",
  [ImportResolution.merge]: "merged into the AD account",
  [ImportResolution.skip]: "skipped",
};

/**
 * Spec 84: search AD users (service account) → multi-select → provision. Spec 88: two steps — the
 * selection is previewed against existing accounts first, so duplicates under an older email
 * address are resolved deliberately rather than silently forking the person into a second account.
 */
export function ImportUsersDialog({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [q, setQ] = useState("");
  const debounced = useDebounced(q, SEARCH_DEBOUNCE_MS);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [results, setResults] = useState<DirectoryUserImportResult[] | null>(null);
  const [candidates, setCandidates] = useState<ImportCandidate[] | null>(null);
  const [choices, setChoices] = useState<Record<string, ImportResolutionEntry>>({});
  const search = useQuery(directoryUsersQuery(debounced));

  const preview = useMutation({
    mutationFn: (body: DirectoryUserImportRequest) =>
      api.post<ImportCandidate[]>(LdapPath.directoryUsersImportPreview, body),
    onSuccess: (rows) => {
      setCandidates(rows);
      // Seed every row with the server's suggestion so importing straight away does the sensible
      // thing; the admin only touches what they disagree with.
      setChoices(Object.fromEntries(rows.map((row) => [row.email, {
        email: row.email, resolution: row.suggested, target_user_id: row.matches[0]?.user_id ?? null,
      }])));
    },
  });
  const importUsers = useMutation({
    mutationFn: (body: DirectoryUserImportRequest) =>
      api.post<DirectoryUserImportResult[]>(LdapPath.directoryUsersImport, body),
    onSuccess: async (imported) => {
      setResults(imported);
      setSelected(new Set());
      setCandidates(null);
      const created = imported.filter((r) => r.created).length;
      const changed = imported.filter((r) => !r.created && !r.error && r.resolution !== ImportResolution.skip).length;
      toast(`AD import: ${created} created, ${changed} updated`, ToastKind.success);
      await refreshAfterImport(queryClient, AffectedKeys.users, AffectedKeys.usersAdmin);
    },
  });
  const toggle = (email: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(email)) next.delete(email);
      else next.add(email);
      return next;
    });

  // Step 2: decisions first, then the write.
  if (candidates) {
    return (
      <Modal title="Review the AD import" onClose={onClose} wide>
        <div className="flex flex-col gap-3">
          <ImportReview candidates={candidates} choices={choices}
            onChoose={(email, entry) => setChoices((prev) => ({ ...prev, [email]: entry }))} />
          {importUsers.isError && <ErrorText error={importUsers.error} />}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setCandidates(null)}>Back</Button>
            <Button disabled={importUsers.isPending} onClick={() =>
              importUsers.mutate({ emails: candidates.map((c) => c.email), resolutions: Object.values(choices) })}>
              <Download size={14} aria-hidden />
              {importUsers.isPending ? "Importing…" : "Apply import"}
            </Button>
          </div>
        </div>
      </Modal>
    );
  }

  const found = search.data ?? [];
  return (
    <Modal title="Import users from AD" onClose={onClose} wide>
      <div className="flex flex-col gap-3" data-import-users>
        <TextField label="Search the directory" value={q} onChange={(event) => setQ(event.target.value)}
          placeholder="Name, username, or email…" hint="Searches cn / sAMAccountName / mail via the service account." />
        {search.isError ? (
          <ErrorText error={search.error} />
        ) : search.isPending ? (
          <p className="text-xs text-fg-muted">Searching…</p>
        ) : found.length === 0 ? (
          <p className="text-xs text-fg-muted">No directory users match.</p>
        ) : (
          <ul className="flex max-h-64 flex-col gap-1 overflow-y-auto" data-directory-user-results>
            {found.map((user) => (
              <li key={user.email}>
                <label className={pickRowClasses}>
                  <input type="checkbox" checked={selected.has(user.email)} onChange={() => toggle(user.email)}
                    className="mt-0.5 accent-accent" />
                  <span className="min-w-0">
                    <span className="block truncate text-fg">{user.name}</span>
                    <span className="block truncate text-xs text-fg-muted">{user.email} · {user.username}</span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
        )}
        {results && (
          <ImportResults rows={results.map((result) => ({
            key: result.email, label: result.email, failed: Boolean(result.error),
            outcome: result.error ?? RESULT_LABELS[result.resolution] ?? "already exists",
          }))} />
        )}
        {preview.isError && <ErrorText error={preview.error} />}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Close</Button>
          <Button onClick={() => preview.mutate({ emails: [...selected] })} disabled={selected.size === 0 || preview.isPending}>
            <Download size={14} aria-hidden />
            {preview.isPending ? "Checking…" : `Review ${selected.size || ""}`.trim()}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
