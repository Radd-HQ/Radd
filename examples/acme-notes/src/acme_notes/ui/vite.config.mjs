import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { raddRemote } from "@radd/plugin-sdk/vite";

// The acme-notes UI remote (spec 94 acceptance): config comes from the SDK, so an external plugin's
// build is self-contained via its @radd/plugin-sdk dependency. Builds to ./dist/remoteEntry.js,
// which ships inside the acme_notes package and Radd serves at /plugins/acme-notes/.
export default raddRemote(dirname(fileURLToPath(import.meta.url)));
