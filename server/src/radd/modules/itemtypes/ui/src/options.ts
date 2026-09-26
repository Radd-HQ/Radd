import { optionContribution, optionTransport } from "@radd/plugin-sdk";

/** Transport and vocabulary belong to this plugin; controls are generic. */
export const optionContributions = [
  optionContribution({
    resource: "issue-types", noun: "issue types",
    meta: { entities: ["project", "role"] },
    ...optionTransport("/issue-types/options"),
  }),
];
