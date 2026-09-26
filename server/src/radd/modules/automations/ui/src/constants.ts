export const ApiPath = { automations: "/automations" } as const;
export const AUTOMATION_CLEAR_VALUE = "none";
export const apiAutomationPath = (ruleId: string) => `${ApiPath.automations}/${ruleId}`;
export const apiAutomationTestPath = (ruleId: string) =>
  `${ApiPath.automations}/${ruleId}/test`;
export const apiAutomationRunsPath = (ruleId: string) =>
  `${ApiPath.automations}/${ruleId}/runs`;
export const apiAutomationRunPath = (ruleId: string, runId: string) =>
  `${ApiPath.automations}/${ruleId}/runs/${runId}`;
export const apiAutomationVersionsPath = (ruleId: string) =>
  `${ApiPath.automations}/${ruleId}/versions`;
export const apiAutomationVersionPath = (ruleId: string, version: number) =>
  `${ApiPath.automations}/${ruleId}/versions/${version}`;
export const apiAutomationRestorePath = (ruleId: string, version: number) =>
  `${ApiPath.automations}/${ruleId}/versions/${version}/restore`;
