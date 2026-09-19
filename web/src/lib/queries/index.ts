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
export * from "./automations";
export * from "./forms";
export * from "./approvals";
export * from "./timelogging";
export * from "./activity";
export * from "./notifications";
export * from "./service-desk";
export * from "./batches";
export * from "./pages";
export * from "./ai-search";
export * from "./ai-admin";
export * from "./sso-admin";
export * from "./storage-admin";
export * from "./mail-admin";
export * from "./jira";
export * from "./confluence";
export * from "./leave";
export * from "./integrations";
export * from "./scripts";
