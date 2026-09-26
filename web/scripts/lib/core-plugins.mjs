/**
 * The core plugins whose UI is bundled with the host (RADD-1373). A real server always lists them
 * in `/capabilities` `plugins`; a proof's mocked capabilities must too, or the host withdraws their
 * pickers, pages and sources exactly as it would for a server that stopped loading them.
 */
import { discover } from "../plugin-packages.mjs";

export const CORE_PLUGINS = discover().filter((p) => p.bundled).map((p) => p.plugin);
