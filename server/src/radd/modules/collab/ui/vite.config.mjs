import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { raddRemote } from "@radd/plugin-sdk/vite";

export default raddRemote(dirname(fileURLToPath(import.meta.url)));
