import { searchSource } from "./lookups";
import { definePlugin } from "@radd/plugin-sdk";
import { optionContributions } from "./options";

export default definePlugin({ querySources: [searchSource], contributions: optionContributions });
