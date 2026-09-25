import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { raddRemote } from "@radd/plugin-sdk/vite";

// This plugin's UI is a self-contained module-federation remote (spec 94): its config comes from
// the SDK, it externalizes the shared singletons, and it builds to ./dist/remoteEntry.js — which
// Radd serves at /plugins/<name>/ straight from this directory.
export default raddRemote(dirname(fileURLToPath(import.meta.url)));
