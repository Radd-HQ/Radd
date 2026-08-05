import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Download } from "lucide-react";
import { api } from "../../lib/api";
import { ApiPath, SEARCH_DEBOUNCE_MS } from "../../lib/constants";
import { useDebounced } from "../../lib/hooks";
import { ldapDirectoryUsersQuery, ldapGroupsQuery, queryKeys } from "../../lib/queries";
import { pushToast, ToastKind } from "../../lib/toast";
import {
  ImportResolution,
  type DirectoryGroup,
  type DirectoryUserImportRequest,
  type DirectoryUserImportResult,
  type GroupImportRequest,
  type GroupImportResult,
  type ImportCandidate,
  type ImportResolutionEntry,
} from "../../lib/types";
import { Button } from "../Button";
import { Modal } from "../Modal";
import { TextField } from "../TextField";
import { DirectoryImportReview } from "./DirectoryImportReview";
import { ErrorText } from "../ErrorText";

const rowClasses =
  "flex items-start gap-2 rounded-md border border-subtle px-2.5 py-2 text-[13px] " +
  "hover:bg-surface/60 cursor-pointer";

/** What each resolution actually did, for the result list (spec 88). */
const RESULT_LABELS: Record<string, string> = {
  [ImportResolution.create]: "provisioned",
  [ImportResolution.overwrite]: "existing account re-addressed to AD",
  [ImportResolution.merge]: "merged into the AD account",
  [ImportResolution.skip]: "skipped",
};

/**
 * Spec 84: search AD users (service account) → multi-select → provision.
 * Spec 88: two steps — the selection is previewed against existing accounts
 * first, so duplicates under an older email address are resolved deliberately
 * rather than silently forking the person into a second account.
 */
export function ImportUsersDialog({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [q, setQ] = useState("");
  const debounced = useDebounced(q, SEARCH_DEBOUNCE_MS);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [results, setResults] = useState<DirectoryUserImportResult[] | null>(null);
  const [candidates, setCandidates] = useState<ImportCandidate[] | null>(null);
  const [choices, setChoices] = useState<Record<string, ImportResolutionEntry>>({});
  const search = useQuery(ldapDirectoryUsersQuery(debounced));

  const preview = useMutation({
    mutationFn: (body: DirectoryUserImportRequest) =>
      api.post<ImportCandidate[]>(ApiPath.ldapDirectoryUsersImportPreview, body),
    onSuccess: (rows) => {
      setCandidates(rows);
      // Seed every row with the server's suggestion so importing straight away
      // does the sensible thing; the admin only touches what they disagree with.
      setChoices(
        Object.fromEntries(
          rows.map((row) => [
            row.email,
            {
              email: row.email,
              resolution: row.suggested,
              target_user_id: row.matches[0]?.user_id ?? null,
            },
          ]),
        ),
      );
    },
  });

  const importUsers = useMutation({
    mutationFn: (body: DirectoryUserImportRequest) =>
      api.post<DirectoryUserImportResult[]>(ApiPath.ldapDirectoryUsersImport, body),
    onSuccess: async (imported) => {
      setResults(imported);
      setSelected(new Set());
      setCandidates(null);
      const created = imported.filter((r) => r.created).length;
      const changed = imported.filter(
        (r) => !r.created && !r.error && r.resolution !== ImportResolution.skip,
      ).length;
      pushToast(
        `AD import: ${created} created, ${changed} updated`,
        ToastKind.success,
      );
      await queryClient.invalidateQueries({ queryKey: queryKeys.users });
      await queryClient.invalidateQueries({ queryKey: ["usersAdmin"] });
    },
  });

  const toggle = (email: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(email)) next.delete(email);
      else next.add(email);
      return next;
    });
  };

  // Step 2: decisions first, then the write.
  if (candidates) {
    return (
      <Modal title="Review the AD import" onClose={onClose} wide>
        <div className="flex flex-col gap-3">
          <DirectoryImportReview
            candidates={candidates}
            choices={choices}
            onChoose={(email, entry) => setChoices((prev) => ({ ...prev, [email]: entry }))}
          />
          {importUsers.isError && (
            <ErrorText error={importUsers.error} />
          )}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setCandidates(null)}>
              Back
            </Button>
            <Button
              onClick={() =>
                importUsers.mutate({
                  emails: candidates.map((c) => c.email),
                  resolutions: Object.values(choices),
                })
              }
              disabled={importUsers.isPending}
            >
              <Download size={14} aria-hidden />
              {importUsers.isPending ? "Importing…" : "Apply import"}
            </Button>
          </div>
        </div>
      </Modal>
    );
  }

  return (
    <Modal title="Import users from AD" onClose={onClose} wide>
      <div className="flex flex-col gap-3">
        <TextField
          label="Search the directory"
          value={q}
          onChange={(event) => setQ(event.target.value)}
          placeholder="Name, username, or email…"
          hint="Searches cn / sAMAccountName / mail via the service account."
        />
        {search.isError ? (
          <ErrorText error={search.error} />
        ) : search.isPending ? (
          <p className="text-xs text-fg-muted">Searching…</p>
        ) : (search.data ?? []).length === 0 ? (
          <p className="text-xs text-fg-muted">No directory users match.</p>
        ) : (
          <ul className="flex max-h-64 flex-col gap-1 overflow-y-auto">
            {(search.data ?? []).map((user) => (
              <li key={user.email}>
                <label className={rowClasses}>
                  <input
                    type="checkbox"
                    checked={selected.has(user.email)}
                    onChange={() => toggle(user.email)}
                    className="mt-0.5 accent-accent"
                  />
                  <span className="min-w-0">
                    <span className="block truncate text-fg">{user.name}</span>
                    <span className="block truncate text-xs text-fg-muted">
                      {user.email} · {user.username}
                    </span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
        )}
        {results && (
          <ul className="flex flex-col gap-0.5 text-xs">
            {results.map((result) => (
              <li key={result.email} className="flex items-center gap-1.5">
                <Check
                  size={12}
                  className={result.error ? "text-red-400" : "text-emerald-400"}
                  aria-hidden
                />
                <span className="text-fg">{result.email}</span>
                <span className="text-fg-muted">
                  {result.error ?? RESULT_LABELS[result.resolution] ?? "already exists"}
                </span>
              </li>
            ))}
          </ul>
        )}
        {preview.isError && <ErrorText error={preview.error} />}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Close
          </Button>
          <Button
            onClick={() => preview.mutate({ emails: [...selected] })}
            disabled={selected.size === 0 || preview.isPending}
          >
            <Download size={14} aria-hidden />
            {preview.isPending ? "Checking…" : `Review ${selected.size || ""}`.trim()}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

/** Spec 84 §2: search AD groups → multi-select → provision flag → per-group
 * result list (team created/linked, members added, provisioned).
 * Spec 85: `preselected` (the Directory page's table selection) replaces the
 * in-dialog search with a fixed, pre-checked list — same import path. */
export function ImportGroupsDialog({
  onClose,
  preselected,
}: {
  onClose: () => void;
  preselected?: DirectoryGroup[];
}) {
  const queryClient = useQueryClient();
  const [q, setQ] = useState("");
  const debounced = useDebounced(q, SEARCH_DEBOUNCE_MS);
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set((preselected ?? []).map((group) => group.dn)),
  );
  const [provisionMembers, setProvisionMembers] = useState(false);
  const [results, setResults] = useState<GroupImportResult[] | null>(null);
  const search = useQuery({ ...ldapGroupsQuery(debounced), enabled: !preselected });
  const groupList = preselected ?? search.data ?? [];

  const importGroups = useMutation({
    mutationFn: (body: GroupImportRequest) =>
      api.post<GroupImportResult[]>(ApiPath.ldapGroupsImport, body),
    onSuccess: async (imported) => {
      setResults(imported);
      setSelected(new Set());
      const ok = imported.filter((r) => !r.error).length;
      pushToast(`Imported ${ok} group${ok === 1 ? "" : "s"} from AD`, ToastKind.success);
      await queryClient.invalidateQueries({ queryKey: ["teams"] });
      await queryClient.invalidateQueries({ queryKey: ["teamMembers"] });
      await queryClient.invalidateQueries({ queryKey: queryKeys.users });
    },
  });

  const toggle = (dn: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(dn)) next.delete(dn);
      else next.add(dn);
      return next;
    });
  };

  return (
    <Modal title="Import groups from AD" onClose={onClose} wide>
      <div className="flex flex-col gap-3">
        {!preselected && (
          <TextField
            label="Search groups"
            value={q}
            onChange={(event) => setQ(event.target.value)}
            placeholder="Group name (cn)…"
          />
        )}
        {!preselected && search.isError ? (
          <ErrorText error={search.error} />
        ) : !preselected && search.isPending ? (
          <p className="text-xs text-fg-muted">Searching…</p>
        ) : groupList.length === 0 ? (
          <p className="text-xs text-fg-muted">No directory groups match.</p>
        ) : (
          <ul className="flex max-h-56 flex-col gap-1 overflow-y-auto">
            {groupList.map((group) => (
              <li key={group.dn}>
                <label className={rowClasses}>
                  <input
                    type="checkbox"
                    checked={selected.has(group.dn)}
                    onChange={() => toggle(group.dn)}
                    className="mt-0.5 accent-accent"
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-fg">{group.cn}</span>
                    <span className="block truncate text-xs text-fg-muted">
                      {group.description || group.dn}
                    </span>
                  </span>
                  <span className="shrink-0 text-xs text-fg-muted">
                    {group.member_count} direct
                  </span>
                </label>
              </li>
            ))}
          </ul>
        )}
        <div className="flex items-end gap-3">
          <label className="flex h-8 items-center gap-2 text-[13px] text-fg">
            <input
              type="checkbox"
              checked={provisionMembers}
              onChange={(event) => setProvisionMembers(event.target.checked)}
              className="accent-accent"
            />
            Provision unknown members
          </label>
        </div>
        {results && (
          <ul className="flex flex-col gap-0.5 text-xs">
            {results.map((result) => (
              <li key={result.group_dn} className="flex items-center gap-1.5">
                <Check
                  size={12}
                  className={result.error ? "text-red-400" : "text-emerald-400"}
                  aria-hidden
                />
                <span className="text-fg">{result.cn || result.group_dn}</span>
                <span className="text-fg-muted">
                  {result.error ??
                    `${result.created ? "team created" : "team linked"} · +${result.members_added} members · ${result.users_provisioned} provisioned`}
                </span>
              </li>
            ))}
          </ul>
        )}
        {importGroups.isError && (
          <ErrorText error={importGroups.error} />
        )}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Close
          </Button>
          <Button
            onClick={() =>
              importGroups.mutate({
                group_dns: [...selected],
                provision_members: provisionMembers,
              })
            }
            disabled={selected.size === 0 || importGroups.isPending}
          >
            <Download size={14} aria-hidden />
            {importGroups.isPending ? "Importing…" : `Import ${selected.size || ""}`.trim()}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
