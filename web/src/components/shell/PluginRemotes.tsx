import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { syncContributionPrefs } from "@radd/plugin-sdk";
import { capabilitiesQuery } from "../../lib/queries";
import { syncPluginRemotes } from "../../lib/plugin-loader";

/**
 * Drives the plugin UI-remote loader (spec 94). Reads the capabilities manifest and reconciles the
 * loaded federated remotes with the enabled set whenever it changes — so enabling/disabling a plugin
 * in the admin loads/unloads its UI live. Also loads the user's per-contribution prefs from the
 * server (so toggles follow them across browsers). Renders nothing.
 */
export function PluginRemotes() {
  const { data } = useQuery(capabilitiesQuery);
  const remotes = data?.remotes;
  useEffect(() => {
    void syncPluginRemotes(remotes);
  }, [remotes]);
  // Once authenticated (the shell only renders when signed in), pull the server-side prefs.
  useEffect(() => {
    void syncContributionPrefs();
  }, []);
  return null;
}
