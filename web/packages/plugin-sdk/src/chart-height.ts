import { createContext } from "react";

/**
 * The plot height a dashboard widget grants the charts inside it (part of the `dashboard.widget`
 * slot contract, RADD-1393). The dashboards package provides it per widget; the chart kit reads it,
 * so a report drawn in a widget — the host's or a plugin's — fits the widget's height. Outside a
 * dashboard it is undefined and charts keep their own defaults.
 */
export const ChartHeightContext = createContext<number | undefined>(undefined);
