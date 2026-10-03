import type { OrganizerVisit } from "./organizer-api.js";

export function projectDashboardVisits(
  visits: OrganizerVisit[],
  collapsedStates?: OrganizerVisit["state"][],
): {
  drafts: OrganizerVisit[];
  reminders: OrganizerVisit[];
  reminderCount: number;
  visibleReminders: OrganizerVisit[];
};
