/**
 * Shared client constants: routes, API paths, timings, storage keys, report + roadmap tuning.
 *
 * Intentional re-export barrel (split per domain; may exceed 300 lines):
 * every module above keeps `import … from "lib/constants"` working unchanged.
 */
export * from "./routes";
export * from "./api";
export * from "./api-paths";
export * from "./ui";
export * from "./storage";
export * from "./reports";
export * from "./roadmap";
