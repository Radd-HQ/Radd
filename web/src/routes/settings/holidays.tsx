import { TeamHolidaysSection } from "../../components/settings/LeaveSections";
import { SettingsPage } from "../../components/settings/SettingsPage";

/** Settings → Holidays (People group, settings reorg 2026-08-01): instance
 * admins define per-team public holidays — regional teams differ, the point.
 * Personal absences live on the Profile page; the old Settings → Leave page
 * redirects there. Holidays apply to every CURRENT member of the team. */
export function HolidaysSettingsPage() {
  return (
    <SettingsPage
      title="Holidays"
      description="Per-team public holidays. They mark every member away on the timesheet and exempt those days from time-tracking outlier flags."
    >
      <TeamHolidaysSection />
    </SettingsPage>
  );
}
