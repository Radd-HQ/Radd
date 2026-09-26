import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import { api, Button, ButtonVariant, Modal, QueryError, SelectField, TextField } from "@radd/plugin-sdk";
import { ConfluencePath, connectionsQuery, spacesQuery, treeQuery } from "./queries";
import { ConfluenceScopeKind } from "./types";

/** The scope picker: the one place the three selections differ. */
export function DownloadModal({
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

  const [connectionId, setConnectionId] = useState("");
  const connections = useQuery(connectionsQuery());
  const spaces = useQuery(spacesQuery(connectionId || null));

  const start = useMutation({
    mutationFn: () =>
      api.post(ConfluencePath.snapshots, {
        connection_id: connectionId || null,
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
        {start.isError && <QueryError label="start download" error={start.error}/>}
        {connections.isError && <QueryError label="connections" error={connections.error}/>}
        <SelectField label="Source connection" value={connectionId} onChange={e => { setConnectionId(e.target.value); setSpaceKey(""); setRootPageId(""); setPageIds([]); }}>
          <option value="">Default connection</option>
          {(connections.data ?? []).map(c => <option key={c.id} value={c.id}>{c.name} — {c.base_url}</option>)}
        </SelectField>
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
          <div className="max-h-72 overflow-y-auto rounded-lg border border-subtle">
            <PageBranch
              connectionId={connectionId}
              spaceKey={spaceKey}
              parentId=""
              depth={0}
              kind={kind}
              rootPageId={rootPageId}
              pageIds={pageIds}
              onPick={setRootPageId}
              onToggle={(id, on) =>
                setPageIds((current) =>
                  on ? [...current, id] : current.filter((x) => x !== id),
                )
              }
            />
          </div>
        )}
        {kind === ConfluenceScopeKind.pages && pageIds.length > 0 && (
          <p className="text-[12px] text-fg-muted">{pageIds.length} page(s) selected</p>
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

/**
 * One level of the remote tree, fetched when it is opened.
 *
 * The picker used to ask for the whole space at once: 61 requests and over two
 * minutes against a real one, during which it rendered nothing — which reads as
 * "this space is empty", not "still loading". A branch costs one request.
 */
function PageBranch({
  connectionId,
  spaceKey,
  parentId,
  depth,
  kind,
  rootPageId,
  pageIds,
  onPick,
  onToggle,
}: {
  connectionId: string;
  spaceKey: string;
  parentId: string;
  depth: number;
  kind: string;
  rootPageId: string;
  pageIds: string[];
  onPick: (id: string) => void;
  onToggle: (id: string, on: boolean) => void;
}) {
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const level = useQuery(treeQuery(spaceKey, parentId, connectionId || null));

  if (level.isLoading) {
    return <p className="px-3 py-2 text-[13px] text-fg-faint">Loading…</p>;
  }
  if (level.isError) {
    return (
      <p className="px-3 py-2 text-[13px] text-fg-secondary">
        Could not list these pages. The connection works, but the request failed.
      </p>
    );
  }
  const nodes = level.data ?? [];
  if (!nodes.length) {
    return (
      <p className="px-3 py-2 text-[13px] text-fg-faint">
        {depth === 0 ? "This space has no pages." : "No pages below this one."}
      </p>
    );
  }

  return (
    <>
      {nodes.map((node) => (
        <div key={node.id}>
          <div
            className="flex items-center gap-1.5 border-b border-subtle px-2 py-1.5 text-[13px] last:border-0 hover:bg-elevated"
            style={{ paddingLeft: `${8 + depth * 16}px` }}
          >
            <button
              type="button"
              aria-label={open[node.id] ? `Collapse ${node.title}` : `Expand ${node.title}`}
              aria-expanded={Boolean(open[node.id])}
              disabled={!node.has_children}
              onClick={() => setOpen((o) => ({ ...o, [node.id]: !o[node.id] }))}
              className="shrink-0 disabled:opacity-0"
            >
              <ChevronRight
                className={`size-4 text-fg-muted transition-transform ${
                  open[node.id] ? "rotate-90" : ""
                }`}
                aria-hidden
              />
            </button>
            <label className="flex min-w-0 flex-1 cursor-pointer items-center gap-2">
              <input
                type={kind === ConfluenceScopeKind.subtree ? "radio" : "checkbox"}
                name="scope-node"
                checked={
                  kind === ConfluenceScopeKind.subtree
                    ? rootPageId === node.id
                    : pageIds.includes(node.id)
                }
                onChange={(e) =>
                  kind === ConfluenceScopeKind.subtree
                    ? onPick(node.id)
                    : onToggle(node.id, e.target.checked)
                }
              />
              <span className="truncate text-fg">{node.title}</span>
            </label>
          </div>
          {open[node.id] && (
            <PageBranch
              connectionId={connectionId}
              spaceKey={spaceKey}
              parentId={node.id}
              depth={depth + 1}
              kind={kind}
              rootPageId={rootPageId}
              pageIds={pageIds}
              onPick={onPick}
              onToggle={onToggle}
            />
          )}
        </div>
      ))}
    </>
  );
}
