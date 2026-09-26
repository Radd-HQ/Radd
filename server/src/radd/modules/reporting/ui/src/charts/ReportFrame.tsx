import type { ReportCardProps } from "../report-contract";
import { ReportCard } from "./ReportCard";
import { CardBody, ScopeNote } from "./report-state";

/** A report card as a plugin's report sees it (REPORT_CARD_SLOT): the titled card, its scope
 * note and the loading/error/empty gate in one — the same three pieces every host card composes. */
export function ReportFrame({ scope, loading, error, empty, emptyMessage, children, ...card }: ReportCardProps) {
  return (
    <ReportCard {...card} note={<ScopeNote scope={scope} />}>
      <CardBody pending={loading} error={error} empty={empty} emptyMessage={emptyMessage}>
        {children}
      </CardBody>
    </ReportCard>
  );
}
