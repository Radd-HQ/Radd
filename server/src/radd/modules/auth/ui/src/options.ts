import { optionContribution, optionTransport } from "@radd/plugin-sdk";

/** Transport and vocabulary belong to this plugin; controls are generic. */
export const optionContributions = [
  optionContribution({
    resource: "users", noun: "people", hintAfter: true, stacked: true,
    meta: { entities: ["member", "project", "role"] },
    ...optionTransport("/users/options"),
  }),
  optionContribution({
    resource: "users/directory", noun: "people",
    meta: { entities: ["member", "project", "role"] },
    ...optionTransport("/users/directory/options"),
  }),
  optionContribution({
    resource: "roles", noun: "roles",
    meta: { entities: ["role", "project"] },
    ...optionTransport("/roles/options"),
  }),
  optionContribution({
    resource: "roles/assignable", noun: "roles",
    meta: { entities: ["role", "project"] },
    ...optionTransport("/roles/assignable/options"),
  }),
];
