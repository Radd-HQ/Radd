import { Link, useCanGoBack, useParams, useRouter } from "@tanstack/react-router";
import { ArrowLeft } from "lucide-react";
import { RoutePath } from "../lib/constants";
import { useItemByKey } from "../lib/hooks";
import { Spinner } from "../components/Spinner";
import { ItemDetailBody } from "./item-detail";

const backClass =
  "inline-flex items-center gap-1.5 text-xs text-fg-secondary hover:text-heading cursor-pointer";

/**
 * Canonical, key-addressed issue page (route `/issues/$itemKey`, spec 21) — the
 * single full-page issue view every internal link points at (usually reached by
 * expanding the side panel). Resolves the item via the server's by-key resolver,
 * then reuses `ItemDetailBody`. Back returns to wherever you came from (browser
 * history); on a cold/shared load it falls back to the item's project board.
 */
export function ItemDetailPage() {
  const { itemKey = "" } = useParams({ strict: false });
  const router = useRouter();
  const canGoBack = useCanGoBack();
  const { project, item, isPending, isError } = useItemByKey(itemKey);

  const backLink = canGoBack ? (
    <button type="button" onClick={() => router.history.back()} className={backClass}>
      <ArrowLeft size={13} aria-hidden />
      Back
    </button>
  ) : project ? (
    <Link to={RoutePath.project} params={{ projectKey: project.key }} className={backClass}>
      <ArrowLeft size={13} aria-hidden />
      {project.key}
    </Link>
  ) : (
    <Link to={RoutePath.home} className={backClass}>
      <ArrowLeft size={13} aria-hidden />
      Projects
    </Link>
  );

  return (
    <div className="flex h-full w-full flex-col">
      <div className="border-b border-subtle px-5 py-2.5">{backLink}</div>
      {isError || project === null ? (
        <p className="p-6 text-sm text-fg-muted">Item {itemKey} not found.</p>
      ) : isPending || !project || !item ? (
        <Spinner label="Loading item…" />
      ) : (
        <ItemDetailBody key={item.id} project={project} item={item} />
      )}
    </div>
  );
}
