import { optionContribution, optionTransport } from "@radd/plugin-sdk";

/** Transport and vocabulary belong to this plugin; controls are generic. */
export const optionContributions = [
  optionContribution({
    resource: "page-spaces", noun: "wiki spaces",
    meta: { entities: ["docSpace", "project", "role"] },
    ...optionTransport("/page-spaces/options"),
  }),
];
