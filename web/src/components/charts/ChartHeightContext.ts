import { createContext } from "react";

/** Dashboard cards supply their available plot height; standalone charts keep their defaults. */
export const ChartHeightContext = createContext<number | undefined>(undefined);
