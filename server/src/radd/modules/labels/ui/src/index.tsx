import { definePlugin } from "@radd/plugin-sdk";
import { catalogSource } from "./catalog";
export default definePlugin({ querySources: [catalogSource] });
