import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { syncContributionPrefs } from "@radd/plugin-sdk";
import { useIsAuthenticated } from "../../lib/hooks";
import { capabilitiesQuery } from "../../lib/queries";
import { syncPluginRemotes, syncStaticPlugins } from "../../lib/plugin-loader";

/** Drives the plugin UI loader: reconciles loaded remotes and bundled core plugins with the
 *  manifest's enabled set (so enable/disable is live) and loads the user's contribution prefs. */
export function PluginRemotes() {
  const { data } = useQuery({...capabilitiesQuery, refetchInterval: 15000});
  const remotes = data?.remotes;
  const plugins = data?.plugins;
  const authenticated = useIsAuthenticated();
  useEffect(() => {
    void syncPluginRemotes(remotes);
  }, [remotes]);
  // Bundled core plugins follow the server's loaded set (RADD-1373).
  useEffect(() => {
    if (plugins) syncStaticPlugins(plugins);
  }, [plugins]);
  // Once a real account is signed in, pull the server-side prefs (spec 121:
  // the shell also renders for an anonymous visitor, who has none).
  useEffect(() => {
    if (authenticated) void syncContributionPrefs();
  }, [authenticated]);
  return null;
}
