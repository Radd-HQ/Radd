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
  // eslint-disable-next-line no-var
  var __RADD_SHARED_LAZY__: Record<string, () => Promise<unknown>> | undefined;
}

/**
 * The editor runtime, shared LAZILY (RADD-1397). The host's editor engine is a chunk that loads
 * when an editor first mounts, so publishing it here would put it in every page's first load.
 * The host registers loaders instead, and the `/shared/prosemirror-*.js` shims await them: a
 * remote that extends the editor — a live binding's ProseMirror plugins — runs against the very
 * module instances the host's editor does, which is what makes its plugin keys, `instanceof`
 * checks and nodes match. They are loaded through the paths the editor itself imports them by.
 */
globalThis.__RADD_SHARED_LAZY__ = {
  "prosemirror-model": () => import("@milkdown/kit/prose/model"),
  "prosemirror-state": () => import("@milkdown/kit/prose/state"),
  "prosemirror-view": () => import("@milkdown/kit/prose/view"),
};

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
