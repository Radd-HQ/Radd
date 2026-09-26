import { definePlugin } from "@radd/plugin-sdk";

/**
 * The dashboards plugin's bundled UI (RADD-1393). Dashboards is core: the host's router, My Work
 * page and sidebar import this package's page, canvas and sidebar pieces through its declared
 * exports (`./page`, `./my-work`, `./sidebar`, `./queries`), so there is nothing to register at
 * boot — plugins join the canvas through the SDK's `dashboard.widget` slot instead.
 */
export default definePlugin({ contributions: [] });
