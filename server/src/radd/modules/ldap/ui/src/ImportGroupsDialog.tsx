import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { api, Button, ErrorText, Modal, toast, ToastKind } from "@radd/plugin-sdk";
import { ImportResults, pickRowClasses } from "./ImportResults";
import { refreshAfterImport } from "./queries";
import { AffectedKeys, LdapPath, type DirectoryGroup, type GroupImportResult } from "./types";

/** Spec 84 §2: the groups picked in the browse table → provision flag → per-group result list
 *  (team created/linked, members added, provisioned). */
export function ImportGroupsDialog({ onClose, preselected }: { onClose: () => void; preselected: DirectoryGroup[] }) {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<Set<string>>(() => new Set(preselected.map((group) => group.dn)));
  const [provisionMembers, setProvisionMembers] = useState(false);
  const [results, setResults] = useState<GroupImportResult[] | null>(null);

  const importGroups = useMutation({
    mutationFn: () =>
      api.post<GroupImportResult[]>(LdapPath.groupsImport, { group_dns: [...selected], provision_members: provisionMembers }),
    onSuccess: async (imported) => {
      setResults(imported);
      setSelected(new Set());
      const ok = imported.filter((r) => !r.error).length;
      toast(`Imported ${ok} group${ok === 1 ? "" : "s"} from AD`, ToastKind.success);
      await refreshAfterImport(queryClient, AffectedKeys.teams, AffectedKeys.teamMembers, AffectedKeys.users,
        AffectedKeys.groups);
    },
  });
  const toggle = (dn: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(dn)) next.delete(dn);
      else next.add(dn);
      return next;
    });

  return (
    <Modal title="Import groups from AD" onClose={onClose} wide>
      <div className="flex flex-col gap-3">
        <ul className="flex max-h-56 flex-col gap-1 overflow-y-auto">
          {preselected.map((group) => (
            <li key={group.dn}>
              <label className={pickRowClasses}>
                <input type="checkbox" checked={selected.has(group.dn)} onChange={() => toggle(group.dn)}
                  className="mt-0.5 accent-accent" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-fg">{group.cn}</span>
                  <span className="block truncate text-xs text-fg-muted">{group.description || group.dn}</span>
                </span>
                <span className="shrink-0 text-xs text-fg-muted">{group.member_count} direct</span>
              </label>
            </li>
          ))}
        </ul>
        <label className="flex h-8 items-center gap-2 text-[13px] text-fg">
          <input type="checkbox" checked={provisionMembers} onChange={(event) => setProvisionMembers(event.target.checked)}
            className="accent-accent" />
          Provision unknown members
        </label>
        {results && (
          <ImportResults rows={results.map((result) => ({
            key: result.group_dn, label: result.cn || result.group_dn, failed: Boolean(result.error),
            outcome: result.error ??
              `${result.created ? "team created" : "team linked"} · +${result.members_added} members · ${result.users_provisioned} provisioned`,
          }))} />
        )}
        {importGroups.isError && <ErrorText error={importGroups.error} />}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Close</Button>
          <Button onClick={() => importGroups.mutate()} disabled={selected.size === 0 || importGroups.isPending}>
            <Download size={14} aria-hidden />
            {importGroups.isPending ? "Importing…" : `Import ${selected.size || ""}`.trim()}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
