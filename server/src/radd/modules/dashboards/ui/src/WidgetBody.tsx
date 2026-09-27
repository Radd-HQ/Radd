import { MissingPluginType, ReportWidget, SlotId, useDisabledMatches, useSlotMatch } from "@radd/plugin-sdk";
import { ActivityWidget } from "./ActivityWidget";
import { SlqCountCard, SlqListCard, ViewCountCard } from "./SlqWidgets";
import { PersonalWidgetType, WidgetType, type DashboardWidget } from "./types";
import { REPORT_TYPES } from "./widget-meta";

/**
 * One widget's body: builtin SLQ/view widgets read the owners' endpoints, report types are the
 * host's cards (SDK `ReportWidget`), and everything else — a plugin's type — renders through
 * `dashboard.widget`. A refused fetch reads as Unavailable; the dashboard never dies.
 */
export function WidgetBody({ widget, filterQuery }: {
  widget: DashboardWidget;
  /** The page-wide SLQ filter. Every builtin honours it; a plugin widget decides for itself. */
  filterQuery?: string;
}) {
  const pluginWidget = useSlotMatch(SlotId.dashboardWidget, widget.widget_type);
  const disabledWidgetTypes = useDisabledMatches(SlotId.dashboardWidget);
  if (REPORT_TYPES.includes(widget.widget_type)) {
    return <ReportWidget widgetType={widget.widget_type} config={{ ...widget.config }} title={widget.title} filterQuery={filterQuery} />;
  }
  switch (widget.widget_type) {
    case WidgetType.slqCount:
      return <SlqCountCard widget={widget} filterQuery={filterQuery} />;
    case WidgetType.slqList:
      return <SlqListCard widget={widget} filterQuery={filterQuery} />;
    case WidgetType.viewCount:
      return <ViewCountCard widget={widget} filterQuery={filterQuery} />;
    case PersonalWidgetType.activity:
      return <ActivityWidget key={JSON.stringify(widget.config)} config={widget.config} />;
    default:
      // Turned off (still in the manifest) or its plugin is gone — the notice tells the two apart.
      return pluginWidget ? (
        <>{pluginWidget.contribution.render({ config: widget.config, widget, filterQuery })}</>
      ) : (
        <MissingPluginType typeKey={widget.widget_type} kind="widget" disabled={disabledWidgetTypes.has(widget.widget_type)} />
      );
  }
}
