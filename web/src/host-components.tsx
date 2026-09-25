/**
 * The host's rich controls, handed to the plugin SDK (RADD-1325) so a plugin's
 * UI bundle renders the same code editor, token list and schema form as core
 * forms do — without bundling CodeMirror into every remote. CodeMirror stays
 * lazy: it loads when an editor first renders, not with the app shell.
 */
import { Suspense, lazy } from "react";
import { provideHostComponents } from "@radd/plugin-sdk";
import { TokenMultiSelect } from "./components/TokenMultiSelect";
import { SchemaFields } from "./components/automations/SchemaFields";

const PythonEditor = lazy(() =>
  import("./components/scripts/PythonEditor").then((module) => ({ default: module.PythonEditor })),
);

provideHostComponents({
  CodeEditor: ({ value, onChange, minHeight }) => (
    <Suspense fallback={<div style={{ minHeight: minHeight ?? 160 }} />}>
      <PythonEditor value={value} onChange={onChange} minHeight={minHeight} />
    </Suspense>
  ),
  TokenList: ({ value, onChange, placeholder, ariaLabel }) => (
    <TokenMultiSelect
      value={value}
      onChange={onChange}
      options={[]}
      placeholder={placeholder}
      ariaLabel={ariaLabel ?? "Values"}
      allowCreate
    />
  ),
  SchemaForm: ({ schema, params, onChange }) => (
    <SchemaFields schema={schema} params={params} onChange={onChange} />
  ),
});
