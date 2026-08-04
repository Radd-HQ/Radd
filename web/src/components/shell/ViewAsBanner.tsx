import { Eye } from "lucide-react";
import { api } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import { useCurrentUser } from "../../lib/hooks";

/**
 * The unmissable strip while an admin previews another account (RADD-836 U1).
 *
 * The server enforces read-only at the auth seam; this banner exists so the
 * admin can never FORGET they are previewing — which is why it is loud, fixed
 * in the shell, and carries the only exit. Exiting reloads the app outright:
 * every cache in the client was filled as the previewed user and none of it
 * may survive the switch back.
 */
export function ViewAsBanner() {
  const me = useCurrentUser();
  if (!me?.view_as) return null;

  const exit = async () => {
    await api.delete(ApiPath.viewAs);
    window.location.assign("/");
  };

  return (
    <div className="flex items-center justify-center gap-2 border-b border-amber-500/40 bg-amber-500/15 px-4 py-1.5 text-xs text-heading">
      <Eye size={13} aria-hidden className="text-amber-400" />
      <span>
        Previewing as <strong>{me.name}</strong> — read-only. You are{" "}
        {me.view_as.real_name}.
      </span>
      <button
        type="button"
        onClick={() => void exit()}
        className="rounded border border-strong px-2 py-0.5 font-medium text-fg hover:bg-elevated cursor-pointer"
      >
        Exit preview
      </button>
    </div>
  );
}
