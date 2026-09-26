/**
 * The shell surfaces the SDK hands to plugin UI (RADD-1393): the SLQ editor and top-bar filter,
 * the saved-view picker, the sharing editor, the report cards, and issue links + the peek panel —
 * what the bundled dashboards package and the approvals remote draw with but cannot import. The
 * heavy ones load when a plugin first renders them, never with the app shell.
 */
import { Suspense, lazy } from "react";
import { provideHostComponents, type ItemPeekProps, type PageQueryFilterProps } from "@radd/plugin-sdk";
import { ItemKeyLink } from "./components/items/ItemBadges";
import { MissingPluginType } from "./components/shell/MissingPluginType";
import { TopBarQuery } from "./components/shell/TopBarSlot";
import { usePeek } from "./lib/hooks";
import { useSlqQueryState } from "./lib/slq-filter";

const QueryBar = lazy(() => import("./components/views/QueryBar").then((m) => ({ default: m.QueryBar })));
const SlqField = lazy(() => import("./components/views/SlqField").then((m) => ({ default: m.SlqField })));
const ViewSelect = lazy(() => import("./components/views/ViewSelect").then((m) => ({ default: m.ViewSelect })));
const SharingDialog = lazy(() => import("./components/views/SharingDialog").then((m) => ({ default: m.SharingDialog })));
const ReportWidget = lazy(() => import("./components/reports/ReportWidget").then((m) => ({ default: m.ReportWidget })));

/** The page's SLQ filter: URL-carried, typed in the top bar, committed on Enter. */
function PageQueryFilter({ placeholder, children }: PageQueryFilterProps) {
  const filter = useSlqQueryState();
  return <>
    <TopBarQuery><Suspense fallback={null}><QueryBar filter={filter} placeholder={placeholder} /></Suspense></TopBarQuery>
    {children(filter.committed)}
  </>;
}

function ItemPeek({ itemKey, children }: ItemPeekProps) {
  const peek = usePeek();
  return <>{children(() => peek.open(itemKey))}</>;
}

provideHostComponents({
  PageQueryFilter,
  ItemPeek,
  ItemKeyLink,
  MissingPluginType,
  SlqField: (props) => <Suspense fallback={null}><SlqField {...props} /></Suspense>,
  ViewSelect: (props) => <Suspense fallback={null}><ViewSelect {...props} /></Suspense>,
  SharingDialog: (props) => <Suspense fallback={null}><SharingDialog {...props} /></Suspense>,
  ReportWidget: (props) => <Suspense fallback={null}><ReportWidget {...props} /></Suspense>,
});
