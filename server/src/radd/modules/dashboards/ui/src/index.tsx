import { definePlugin } from "@radd/plugin-sdk";

/** Dashboards is core (RADD-1393): the host imports this package's page, canvas and sidebar through
 *  its declared exports, so nothing registers at boot; plugins join through `dashboard.widget`. */
export default definePlugin({ contributions: [] });
