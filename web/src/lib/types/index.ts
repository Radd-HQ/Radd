/**
 * Hand-written mirrors of the backend schemas (specs 01–03 + /openapi.json).
 * Keep in sync when backend contracts change.
 *
 * Intentional re-export barrel (split per domain; may exceed 300 lines):
 * every module above keeps `import … from "lib/types"` working unchanged.
 */
export * from "./plugins";
export * from "./settings";
export * from "./permissions";
export * from "./users";
export * from "./jira-import";
export * from "./confluence-import";
export * from "./backups";
export * from "./teams";
export * from "./workflow";
export * from "./approvals";
export * from "./items";
export * from "./cycles";
export * from "./grants";
export * from "./link-types";
export * from "./fields";
export * from "./labels";
export * from "./comments";
export * from "./views";
export * from "./dashboards";
export * from "./reporting";
export * from "./automations";
export * from "./forms";
export * from "./csat";
export * from "./timelogging";
export * from "./history";
export * from "./integrations";
export * from "./notifications";
export * from "./attachments";
export * from "./storage";
export * from "./service-desk";
export * from "./search";
export * from "./pages";
export * from "./ai";
export * from "./sso";
export * from "./leave";
export * from "./monitoring";
