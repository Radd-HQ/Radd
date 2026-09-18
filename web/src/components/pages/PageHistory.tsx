import { useIsAuthenticated } from "../../lib/hooks";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArchiveRestore, ChevronLeft, GitCompare } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { Entity, invalidateEntities } from "../../lib/cache";
import { apiPageRestorePath } from "../../lib/constants";
import { Markdown } from "../../lib/markdown";
import { pageVersionQuery, pageVersionsQuery, usersQuery } from "../../lib/queries";
import type { Page } from "../../lib/types";
import { Button } from "../Button";
import { PageVersionDiff } from "./PageVersionDiff";
import { Spinner } from "../Spinner";
import { relativeTime } from "../../lib/dates";
import { ErrorText } from "../ErrorText";

/**
 * History tab (spec 43): past versions (the CURRENT content is v{page.version},
 * not listed) → view one → Restore, which writes the old content as a NEW
 * version (history stays linear; nothing is overwritten).
 */
export function PageHistory({ page, canWrite }: { page: Page; canWrite: boolean }) {
  const [viewing, setViewing] = useState<number | null>(null);
  // RADD-720: which version to diff against its SUCCESSOR — the comparison a
  // reader wants from a history list is "what did this edit change", so each row
  // offers exactly that rather than making them pick two ends.
  const [diffing, setDiffing] = useState<number | null>(null);
  const versions = useQuery(pageVersionsQuery(page.id));
  const { data: users } = useQuery({ ...usersQuery, enabled: useIsAuthenticated() });

  if (versions.isPending) return <Spinner label="Loading history…" />;
  if (versions.isError) {
    return (
      <p className="mt-3 text-xs text-red-400">
        Failed to load history: {errorMessage(versions.error)}
      </p>
    );
  }

  if (diffing !== null) {
    const list = versions.data;
    const successor = list.find((v) => v.version === diffing + 1);
    return (
      <PageVersionDiff
        page={page}
        from={diffing}
        to={successor ? successor.version : page.version}
        onBack={() => setDiffing(null)}
      />
    );
  }

  if (viewing !== null) {
    return (
      <VersionViewer
        page={page}
        version={viewing}
        canWrite={canWrite}
        onBack={() => setViewing(null)}
      />
    );
  }

  const list = versions.data;
  return (
    <div className="mt-3">
      <p className="mb-2 px-1 text-xs text-fg-muted">
        v{page.version} is the current version{list.length > 0 ? "; earlier versions:" : "."}
      </p>
      {list.length === 0 ? (
        <p className="px-1 text-[13px] text-fg-faint">No earlier versions yet.</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {list.map((version) => (
            <li key={version.version} className="group/version flex items-center gap-1">
              <button
                type="button"
                onClick={() => setViewing(version.version)}
                className="flex min-w-0 flex-1 items-center gap-2 rounded-md border border-subtle bg-surface/50 px-2.5 py-1.5 text-left hover:border-strong cursor-pointer"
              >
                <span className="rounded bg-elevated px-1.5 py-px font-mono text-[10px] text-fg-secondary">
                  v{version.version}
                </span>
                <span className="min-w-0 flex-1 truncate text-[13px] text-fg">
                  {version.title}
                </span>
                <span className="shrink-0 text-[11px] text-fg-muted">
                  {users?.find((user) => user.id === version.author_id)?.name ?? "someone"} ·{" "}
                  <span title={version.created_at}>{relativeTime(version.created_at)}</span>
                </span>
              </button>
              {/* RADD-720: restore was a guess without this — you could roll back
                  to a version you had no way to read the difference of. */}
              <button
                type="button"
                onClick={() => setDiffing(version.version)}
                title={`Compare v${version.version} with what came next`}
                aria-label={`Compare version ${version.version} with the next version`}
                className="shrink-0 rounded p-1.5 text-fg-faint hover:bg-elevated hover:text-fg cursor-pointer"
              >
                <GitCompare size={13} aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function VersionViewer({
  page,
  version,
  canWrite,
  onBack,
}: {
  page: Page;
  version: number;
  canWrite: boolean;
  onBack: () => void;
}) {
  const queryClient = useQueryClient();
  const content = useQuery(pageVersionQuery(page.id, version));
  const restore = useMutation({
    mutationFn: () => api.post<Page>(apiPageRestorePath(page.id), { version }),
    onSuccess: onBack,
    onSettled: () => void invalidateEntities(queryClient, Entity.page, Entity.docSpace),
  });

  return (
    <div className="mt-3">
      <div className="mb-2 flex items-center gap-2">
        <button
          type="button"
          onClick={onBack}
          className="flex items-center gap-1 rounded px-1.5 py-0.5 text-xs text-fg-secondary hover:text-fg cursor-pointer"
        >
          <ChevronLeft size={13} aria-hidden />
          All versions
        </button>
        <span className="rounded bg-elevated px-1.5 py-px font-mono text-[10px] text-fg-secondary">
          v{version}
        </span>
        {canWrite && (
          <Button
            size="sm"
            variant="secondary"
            className="ml-auto"
            onClick={() => restore.mutate()}
            disabled={restore.isPending}
          >
            <ArchiveRestore size={12} aria-hidden />
            {restore.isPending ? "Restoring…" : `Restore v${version}`}
          </Button>
        )}
      </div>
      {restore.isError && (
        <ErrorText className="mb-2" error={restore.error} />
      )}
      {content.isPending ? (
        <Spinner label="Loading version…" />
      ) : content.isError ? (
        <ErrorText error={content.error} />
      ) : (
        <div className="rounded-md border border-subtle bg-surface/40 px-3 py-2">
          <h2 className="mb-2 text-base font-semibold text-heading">{content.data.title}</h2>
          {content.data.body ? (
            <Markdown text={content.data.body} />
          ) : (
            <p className="text-[13px] text-fg-faint">This version had no content.</p>
          )}
        </div>
      )}
    </div>
  );
}
