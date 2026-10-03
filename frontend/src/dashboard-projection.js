export function projectDashboardVisits(visits, collapsedStates = []) {
  const drafts = visits.filter((visit) => visit.state === "draft");
  const reminders = visits.filter((visit) => visit.state !== "draft");
  const collapsed = new Set(collapsedStates);
  const visibleReminders = reminders.filter((visit) => !collapsed.has(visit.state));
  return {
    drafts,
    reminders,
    reminderCount: reminders.length,
    visibleReminders,
  };
}
