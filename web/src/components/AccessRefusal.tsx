import { useQuery } from "@tanstack/react-query";
import { queryOptions } from "@tanstack/react-query";
import { ShieldX } from "lucide-react";
import { api, ApiError, errorMessage } from "../lib/api";
import { ApiPath } from "../lib/constants";

/** GET /permissions/grant-help — who can fix this refusal (RADD-836 U3). */
interface GrantHelp {
  permission: string;
  scope: string;
  granters: string[];
}

const grantHelpQuery = (permission: string, projectId?: string) =>
  queryOptions({
    queryKey: ["grant-help", permission, projectId ?? null] as const,
    queryFn: () =>
      api.get<GrantHelp>(
        `${ApiPath.permissions}/grant-help?permission=${encodeURIComponent(permission)}` +
          (projectId ? `&project_id=${projectId}` : ""),
      ),
    staleTime: 300_000,
  });

/** `"permission 'item.read' denied on project TD"` → the atom, if present. */
function requiredAtom(detail: string): string | null {
  const match = /permission '([a-z_.@]+)'/.exec(detail);
  return match ? match[1] : null;
}

/**
 * A REAL refusal (RADD-836 U3): what is required, at which scope, and who can
 * grant it — instead of a dead-end toast. Rendered by QueryError whenever a
 * load fails with 403, so every route-level surface inherits it at once.
 */
export function AccessRefusal({ error, projectId }: { error: ApiError; projectId?: string }) {
  const detail = errorMessage(error);
  const atom = requiredAtom(detail);
  const help = useQuery({ ...grantHelpQuery(atom ?? "", projectId), enabled: atom !== null });

  return (
    <div className="w-full rounded-lg border border-subtle p-5">
      <p className="flex items-center gap-2 text-sm font-medium text-heading">
        <ShieldX size={16} className="text-red-400" aria-hidden />
        You don't have access to this
      </p>
      <p className="mt-1.5 text-xs text-fg-muted">{detail}</p>
      {atom && (
        <p className="mt-2 text-xs text-fg-secondary">
          Requires <span className="font-mono text-fg">{atom}</span>
          {help.data ? ` (a ${help.data.scope}-scope permission)` : ""}.
        </p>
      )}
      {(help.data?.granters.length ?? 0) > 0 && (
        <p className="mt-1 text-xs text-fg-muted">
          People who can grant it: <span className="text-fg">{help.data!.granters.join(", ")}</span>
        </p>
      )}
    </div>
  );
}
