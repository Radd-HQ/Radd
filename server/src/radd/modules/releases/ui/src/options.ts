import { optionContribution, optionTransport } from "@radd/plugin-sdk";

/** Transport and vocabulary belong to this plugin; controls are generic. */
export const optionContributions = [
  optionContribution({
    resource: "releases", noun: "release versions",
    meta: { entities: ["release", "project", "role"] },
    ...optionTransport("/releases/options"),
  }),
];
