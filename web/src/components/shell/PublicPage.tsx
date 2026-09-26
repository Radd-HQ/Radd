import { SlotId } from "@radd/plugin-sdk";
import { RaddTile } from "../RaddMark";
import { ContributedPage } from "./ContributedPage";
import { PluginRemotes } from "./PluginRemotes";

/**
 * A PUBLIC page (RADD-1401): what someone who holds a link rather than an account lands on — a
 * tokened link in an email. Outside the app shell and the sign-in gate; the page itself is a
 * plugin's `public.page` contribution, matched by path, so the host names none of them.
 *
 * The host draws only the frame — the brand and a reading column — and runs the plugin loader
 * here too, since the shell that normally runs it is not mounted. A visitor loads exactly what
 * spec 121's visitor shell loads: `/capabilities` and the enabled remotes, both answered for the
 * Anyone principal. The route resolves the visitor first (router.tsx), so a refusal on this page
 * is an answer, never a redirect to sign in.
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
