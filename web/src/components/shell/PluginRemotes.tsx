import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { syncContributionPrefs } from "@radd/plugin-sdk";
import { useIsAuthenticated } from "../../lib/hooks";
import { capabilitiesQuery } from "../../lib/queries";
import { syncPluginRemotes } from "../../lib/plugin-loader";

/**
 * Drives the plugin UI-remote loader (spec 94). Reads the capabilities manifest and reconciles the
 * loaded federated remotes with the enabled set whenever it changes — so enabling/disabling a plugin
 * in the admin loads/unloads its UI live. Also loads the user's per-contribution prefs from the
 * server (so toggles follow them across browsers). Renders nothing.
 */
export function PluginRemotes() {
  const { data } = useQuery({...capabilitiesQuery, refetchInterval: 15000});
  const remotes = data?.remotes;
  const authenticated = useIsAuthenticated();
  useEffect(() => {
    void syncPluginRemotes(remotes);
  }, [remotes]);
  // Once a real account is signed in, pull the server-side prefs (spec 121:
  // the shell also renders for an anonymous visitor, who has none).
  useEffect(() => {
    if (authenticated) void syncContributionPrefs();
  }, [authenticated]);
  return null;
}
