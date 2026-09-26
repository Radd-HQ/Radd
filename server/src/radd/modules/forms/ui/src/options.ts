import { optionContribution, optionTransport } from "@radd/plugin-sdk";

/** Transport and vocabulary belong to this plugin; controls are generic. */
export const optionContributions = [
  optionContribution({
    resource: "forms", noun: "intake forms",
    meta: { entities: ["form", "project", "role"] },
    ...optionTransport("/forms/options"),
  }),
];
