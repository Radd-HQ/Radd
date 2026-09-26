/**
 * TanStack Query option factories for every API read.
 *
 * Intentional re-export barrel (split per domain; may exceed 300 lines):
 * every module above keeps `import … from "lib/queries"` working unchanged.
 */
export * from "./shared";
export * from "./core";
export * from "./projects";
export * from "./items";
export * from "./fields";
export * from "./users";
export * from "./views";
export * from "./shared-directories";
export * from "./roles";
export * from "./cycles";
export * from "./reports";
export * from "./forms";
export * from "./timelogging";
export * from "./activity";
export * from "./notifications";
export * from "./service-desk";
export * from "./batches";
export * from "./search";
export * from "./storage-admin";
export * from "./integrations";
