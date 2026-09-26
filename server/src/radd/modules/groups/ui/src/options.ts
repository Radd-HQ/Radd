import { optionContribution, optionTransport } from "@radd/plugin-sdk";

/** Transport and vocabulary belong to this plugin; controls are generic. */
export const optionContributions = [
  optionContribution({
    resource: "groups", noun: "directory groups",
    meta: { entities: ["group", "project", "role"] },
    ...optionTransport("/groups/options"),
  }),
];
