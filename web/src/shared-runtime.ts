/**
 * Populate the shared federation scope (spec 94). The host bundles ONE instance of each shared dep;
 * this module publishes those instances on `globalThis.__RADD_SHARED__`, which the generated
 * `/shared/*.js` shims re-export. A plugin remote's externalized `import ... from "react"` resolves
 * (via the index.html import map) to a shim → this exact instance. Imported FIRST in main.tsx so the
 * scope is populated before any remote loads.
 */
import * as React from "react";
import * as ReactJsxRuntime from "react/jsx-runtime";
import * as ReactJsxDevRuntime from "react/jsx-dev-runtime";
import * as ReactDom from "react-dom";
import * as ReactDomClient from "react-dom/client";
import * as ReactQuery from "@tanstack/react-query";
import * as ReactRouter from "@tanstack/react-router";
import * as PluginSdk from "@radd/plugin-sdk";
import "@radd/plugin-sdk/styles.css";

declare global {
  // eslint-disable-next-line no-var
  var __RADD_SHARED__: Record<string, unknown> | undefined;
}

globalThis.__RADD_SHARED__ = {
  react: React,
  "react/jsx-runtime": ReactJsxRuntime,
  "react/jsx-dev-runtime": ReactJsxDevRuntime,
  "react-dom": ReactDom,
  "react-dom/client": ReactDomClient,
  "@tanstack/react-query": ReactQuery,
  "@tanstack/react-router": ReactRouter,
  "@radd/plugin-sdk": PluginSdk,
};
