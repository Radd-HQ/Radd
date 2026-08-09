import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Trash2, X } from "lucide-react";
import { Button, ButtonVariant } from "../../Button";
import { Modal } from "../../Modal";
import { SelectField } from "../../SelectField";
import { TextField } from "../../TextField";
import { useConfirm } from "../../ConfirmDialog";
import { api } from "../../../lib/api";
import { ApiPath } from "../../../lib/constants";
import {
  confluenceSnapshotsQuery,
  confluenceSpacesQuery,
  confluenceTreeQuery,
  queryKeys,
} from "../../../lib/queries";
import {
  ConfluenceScopeKind,
  CONFLUENCE_STAGE_LABELS,
  CONFLUENCE_TERMINAL_STAGES,
  CONFLUENCE_COUNT_LABELS,
  type ConfluenceSnapshot,
} from "../../../lib/types";

/**
 * The cache (spec 117). A selection is downloaded ONCE and every later step reads
 * it — which is what makes "fix a mapping and try again" a loop rather than
 * another download.
 */
export function SnapshotsPanel({
  onPlanFrom,
}: {
  onPlanFrom: (snapshot: ConfluenceSnapshot) => void;
}) {
  const client = useQueryClient();
  const [confirmNode, confirm] = useConfirm();
  const [starting, setStarting] = useState(false);
  const snapshots = useQuery(confluenceSnapshotsQuery());

  const invalidate = () =>
    void client.invalidateQueries({ queryKey: queryKeys.confluenceSnapshots });

  const cancel = useMutation({
    mutationFn: (id: string) => api.post(`${ApiPath.confluenceSnapshots}/${id}/cancel`, {}),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`${ApiPath.confluenceSnapshots}/${id}`),
    onSuccess: invalidate,
  });

  const rows = snapshots.data ?? [];

  return (
    <section className="rounded-xl border border-subtle bg-surface p-4">
      <header className="mb-3 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-heading">Downloads</h2>
          <p className="text-[13px] text-fg-muted">
            A whole space, a section and everything under it, or a set of pages.
          </p>
        </div>
        <Button size="sm" onClick={() => setStarting(true)}>
          <Download className="size-4" aria-hidden /> Download
        </Button>
      </header>

      {rows.length === 0 ? (
        <p className="text-[13px] text-fg-faint">Nothing downloaded yet.</p>
      ) : (
        <ul className="divide-y divide-subtle">
          {rows.map((snapshot) => {
            const terminal = CONFLUENCE_TERMINAL_STAGES.has(snapshot.stage);
            return (
              <li key={snapshot.id} className="flex items-center gap-3 py-2">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13px] font-medium text-heading">
                    {snapshot.name}
                  </p>
                  <p className="truncate text-[12px] text-fg-muted">
                    {CONFLUENCE_STAGE_LABELS[snapshot.stage] ?? snapshot.stage}
                    {snapshot.page_count > 0 && ` · ${snapshot.page_count} pages`}
                    {snapshot.include_history && " · with history"}
                    {snapshot.problems.length > 0 &&
                      ` · ${snapshot.problems.length} problem(s)`}
                  </p>
                  {!terminal && (
                    <p className="mt-1 text-[12px] text-fg-faint">
                      {Object.entries(snapshot.counts)
                        .filter(([key]) => CONFLUENCE_COUNT_LABELS[key])
                        .map(([key, value]) => `${CONFLUENCE_COUNT_LABELS[key]}: ${value}`)
                        .join(" · ")}
                    </p>
                  )}
                </div>
                {snapshot.stage === "done" && (
                  <Button size="sm" onClick={() => onPlanFrom(snapshot)}>
                    Plan
                  </Button>
                )}
                {!terminal && (
                  <Button
                    variant={ButtonVariant.ghost}
                    size="sm"
                    onClick={() => cancel.mutate(snapshot.id)}
                  >
                    <X className="size-4" aria-hidden /> Cancel
                  </Button>
                )}
                <Button
                  variant={ButtonVariant.ghost}
                  size="sm"
                  aria-label={`Delete ${snapshot.name}`}
                  onClick={async () => {
                    if (
                      await confirm({
                        title: `Delete ${snapshot.name}?`,
                        message: "The cached pages and their downloaded files are removed. Anything already imported stays.",
                        confirmLabel: "Delete",
                        danger: true,
                      })
                    ) {
                      remove.mutate(snapshot.id);
                    }
                  }}
                >
                  <Trash2 className="size-4" aria-hidden />
                </Button>
              </li>
            );
          })}
        </ul>
      )}

      {starting && <NewDownloadModal onClose={() => setStarting(false)} onStarted={invalidate} />}
      {confirmNode}
    </section>
  );
}

/** The scope picker: the one place the three selections differ. */
function NewDownloadModal({
  onClose,
  onStarted,
}: {
  onClose: () => void;
  onStarted: () => void;
}) {
  const [kind, setKind] = useState<string>(ConfluenceScopeKind.space);
  const [spaceKey, setSpaceKey] = useState("");
  const [rootPageId, setRootPageId] = useState("");
  const [pageIds, setPageIds] = useState<string[]>([]);
  const [includeHistory, setIncludeHistory] = useState(false);
  const [historyLimit, setHistoryLimit] = useState("");

  const spaces = useQuery(confluenceSpacesQuery(null));
  const tree = useQuery(confluenceTreeQuery(spaceKey, kind !== ConfluenceScopeKind.space));

  const start = useMutation({
    mutationFn: () =>
      api.post(ApiPath.confluenceSnapshots, {
        scope: {
          kind,
          space_key: spaceKey,
          root_page_id: kind === ConfluenceScopeKind.subtree ? rootPageId : "",
          page_ids: kind === ConfluenceScopeKind.pages ? pageIds : [],
        },
        include_history: includeHistory,
        history_limit: historyLimit ? Number(historyLimit) : null,
      }),
    onSuccess: () => {
      onStarted();
      onClose();
    },
  });

  const ready =
    (kind === ConfluenceScopeKind.space && spaceKey) ||
    (kind === ConfluenceScopeKind.subtree && rootPageId) ||
    (kind === ConfluenceScopeKind.pages && pageIds.length > 0);

  return (
    <Modal title="Download from Confluence" onClose={onClose} wide>
      <div className="flex flex-col gap-3">
        <SelectField label="What to bring" value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value={ConfluenceScopeKind.space}>A whole space</option>
          <option value={ConfluenceScopeKind.subtree}>A page and everything under it</option>
          <option value={ConfluenceScopeKind.pages}>Specific pages</option>
        </SelectField>

        <SelectField
          label="Space"
          value={spaceKey}
          onChange={(e) => {
            setSpaceKey(e.target.value);
            setRootPageId("");
            setPageIds([]);
          }}
        >
          <option value="">Choose a space…</option>
          {(spaces.data ?? []).map((space) => (
            <option key={space.key} value={space.key}>
              {space.name} ({space.key})
            </option>
          ))}
        </SelectField>
        {spaces.isError && (
          <p className="text-[12px] text-fg-muted">
            Could not list spaces — check the connection above.
          </p>
        )}

        {kind !== ConfluenceScopeKind.space && spaceKey && (
          <div className="max-h-64 overflow-y-auto rounded-lg border border-subtle">
            {tree.isLoading && <p className="p-3 text-[13px] text-fg-faint">Loading the tree…</p>}
            {(tree.data ?? []).map((node) => (
              <label
                key={node.id}
                className="flex cursor-pointer items-center gap-2 border-b border-subtle px-3 py-1.5 text-[13px] last:border-0 hover:bg-elevated"
              >
                <input
                  type={kind === ConfluenceScopeKind.subtree ? "radio" : "checkbox"}
                  name="scope-node"
                  checked={
                    kind === ConfluenceScopeKind.subtree
                      ? rootPageId === node.id
                      : pageIds.includes(node.id)
                  }
                  onChange={(e) => {
                    if (kind === ConfluenceScopeKind.subtree) {
                      setRootPageId(node.id);
                    } else {
                      setPageIds((current) =>
                        e.target.checked
                          ? [...current, node.id]
                          : current.filter((id) => id !== node.id),
                      );
                    }
                  }}
                />
                <span className="truncate text-fg">{node.title}</span>
              </label>
            ))}
          </div>
        )}

        <label className="flex items-center gap-2 text-[13px] text-fg-secondary">
          <input
            type="checkbox"
            checked={includeHistory}
            onChange={(e) => setIncludeHistory(e.target.checked)}
          />
          Bring version history
        </label>
        {includeHistory && (
          <TextField
            label="Most recent revisions per page"
            type="number"
            value={historyLimit}
            onChange={(e) => setHistoryLimit(e.target.value)}
            hint="Leave empty for all of them. Pages here often sit at 200+ versions."
          />
        )}

        <div className="mt-1 flex justify-end gap-2">
          <Button variant={ButtonVariant.ghost} onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => start.mutate()} disabled={!ready || start.isPending}>
            Start download
          </Button>
        </div>
      </div>
    </Modal>
  );
}
