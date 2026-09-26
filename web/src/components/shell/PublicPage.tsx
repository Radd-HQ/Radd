import { SlotId } from "@radd/plugin-sdk";
import { RaddTile } from "../RaddMark";
import { ContributedPage } from "./ContributedPage";
import { PluginRemotes } from "./PluginRemotes";

/**
 * A PUBLIC page (RADD-1401) for someone holding a tokened link, outside the shell and the sign-in
 * gate: a plugin's `public.page` contribution matched by path. The host draws the frame and runs
 * the plugin loader itself (the shell that normally does is not mounted); a refusal here is an
 * answer, never a redirect to sign in.
 */
export function PublicPage() {
  return (
    <main className="flex min-h-screen justify-center bg-base px-4 py-10 text-fg">
      <div className="w-full max-w-md">
        <div className="mb-6 flex items-center gap-2.5">
          <RaddTile className="size-8 rounded-lg" />
          <h1 className="text-base font-semibold text-heading">Radd</h1>
        </div>
        <ContributedPage slot={SlotId.publicPage} />
      </div>
      <PluginRemotes />
    </main>
  );
}
