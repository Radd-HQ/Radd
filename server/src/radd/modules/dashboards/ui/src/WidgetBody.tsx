import { MissingPluginType, ReportWidget, SlotId, useDisabledMatches, useSlotMatch } from "@radd/plugin-sdk";
import { ActivityWidget } from "./ActivityWidget";
import { SlqCountCard, SlqListCard, ViewCountCard } from "./SlqWidgets";
import { PersonalWidgetType, WidgetType, type DashboardWidget } from "./types";
import { REPORT_TYPES } from "./widget-meta";

/**
 * One widget's body (spec 75). The builtin SLQ and saved-view widgets read the owners' public
 * endpoints here; the report widgets are the host's report cards (the SDK's ReportWidget bridge);
 * everything else — a plugin's type, or a builtin a plugin draws (report_sla is slas',
 * "Awaiting my approval" is approvals') — renders through the `dashboard.widget` slot. A widget
 * whose fetch is refused reads as Unavailable; the dashboard as a whole never dies.
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
