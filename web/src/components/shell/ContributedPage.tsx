import { useSyncExternalStore } from "react";
import { useLocation } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Slot, matchPagePath, usePageMatch, useDisabledMatches, type SlotIdValue } from "@radd/plugin-sdk";
import { capabilitiesQuery } from "../../lib/queries";
import { isBundledPlugin, readRemoteStates, subscribeRemoteStates } from "../../lib/plugin-loader";
import { Spinner } from "../Spinner";
import { QueryError } from "../QueryError";
import { Callout } from "../Callout";
import { MissingPluginType } from "./MissingPluginType";

/**
 * The shell renders contributed pages; no feature names or implementations live here.
 *
 * `match` is the key the page's contribution and nav entry carry — the pathname for a
 * `route.page`/`settings.page`/`public.page`, the segment under a project's settings for a
 * `project.settings.page` (RADD-1396). A contribution's `match` may be a PATTERN whose `$name`
 * segments capture (RADD-1401); the page receives the captures as `params`. `props` are handed to
 * the page beside `path` and `params`.
 */
export function ContributedPage({ slot, match: matchKey, props }: {
  slot: SlotIdValue;
  match?: string;
  props?: Record<string, unknown>;
}) {
  const pathname = useLocation({ select: location => location.pathname });
  const key = matchKey ?? pathname;
  const manifest = useQuery(capabilitiesQuery);
  const states = useSyncExternalStore(subscribeRemoteStates, readRemoteStates);
  const page = usePageMatch(slot, key);
  const disabledMatches = useDisabledMatches(slot);
  const disabled = [...disabledMatches].some(match => matchPagePath(match, key) !== null);
  const failed = <Callout kind="danger" className="m-6" role="alert">This plugin page could not be loaded. Reload the page to retry, or ask an administrator to check the plugin.</Callout>;
  if (disabled) return <MissingPluginType typeKey={key} kind="page" disabled />;
  if (page) {
    return <Slot id={slot} match={page.match} owner={page.plugin} {...props} path={key} params={page.params} errorFallback={failed} />;
  }
  if (manifest.isPending) return <Spinner label="Loading plugin page…" />;
  if (manifest.isError) return <QueryError label="plugin availability" error={manifest.error} />;
  const owner = manifest.data.nav.find(n => n.path === key)?.plugin;
  // A bundled core plugin is never a remote to wait for (RADD-1373), whatever the manifest lists.
  const remotes = (manifest.data.remotes ?? []).filter(r => !isBundledPlugin(r.name) && (!owner || r.name === owner));
  const relevant = states.filter(state => remotes.some(remote => remote.name === state.name));
  if (owner && relevant.some(state => state.status === "errored" || state.status === "incompatible")) return failed;
  if (remotes.some(remote => !states.some(state => state.name === remote.name)) || relevant.some(state => state.status === "loading")) {
    return <Spinner label="Loading plugin page…" />;
  }
  return <Callout kind="warning" className="m-6" data-plugin-missing="page">This page is unavailable. Its plugin may be disabled or may no longer provide this page.</Callout>;
}
