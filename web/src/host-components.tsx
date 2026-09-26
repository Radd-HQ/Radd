/**
 * The host's rich controls, handed to the plugin SDK (RADD-1325) so a plugin's
 * UI bundle renders the same generic code editor and token list as host
 * forms do — without bundling CodeMirror into every remote. CodeMirror stays
 * lazy: it loads when an editor first renders, not with the app shell.
 */
import { Suspense, lazy } from "react";
import { provideHostComponents, TokenMultiSelect } from "@radd/plugin-sdk";
import { DirectoryPager } from "./components/DirectoryPager";
import { ListSearchInput } from "./components/ListSearchInput";
import { Modal } from "./components/Modal";
import { Avatar } from "./components/Avatar";
import { SettingsPage } from "./components/settings/SettingsPage";
import { Button } from "./components/Button";
import { TextField } from "./components/TextField";
import { SelectField } from "./components/SelectField";
import { Callout } from "./components/Callout";
import { QueryError } from "./components/QueryError";
import { ScopedSettingsEditor } from "./components/settings/ScopedSettingsEditor";
import { RoleGrantsSection } from "./components/settings/RoleGrantsSection";
import { pushToast } from "./lib/toast";

const CodeEditor = lazy(() =>
  import("./components/CodeEditor").then((module) => ({ default: module.CodeEditor })),
);

provideHostComponents({
  CodeEditor: props => (
    <Suspense fallback={<div style={{ minHeight: props.minHeight ?? 160 }} />}>
      <CodeEditor {...props} />
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
  // Page frames and generic form primitives are platform-owned, shared by every remote.
  DirectoryPager, ListSearchInput,
  Modal: props => <Modal {...props} title={props.title ?? ""} />,
  SettingsPage, Avatar, Button, SelectField, Callout, QueryError,
  TextField: props => <TextField {...props} label={props.label ?? ""} />,
  // Platform surfaces a plugin's settings page renders for its own section or subjects (RADD-1377).
  ScopedSettings: ScopedSettingsEditor,
  RoleGrants: RoleGrantsSection,
  toast: (message, kind) => pushToast(message, kind),
});
