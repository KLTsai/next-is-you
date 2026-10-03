import test from "node:test";
import assert from "node:assert/strict";
import { projectDashboardVisits } from "../src/dashboard-projection.js";

const states = ["draft", "active", "stopping", "stopped", "expired"];
const visits = states.map((state, index) => ({
  id: `visit-${index}`,
  state,
  hospital: "ntuh-main",
  date: "2026-10-03",
  department_code: "MED",
  clinic_code: "MED-101",
  session: "morning",
  observation: { current_number: null, checked_at: null },
  source_read: { status: "usable", reason: "none" },
  notification: { count: 0, accepted: 0, issues: 0 },
  recipients: [],
}));

test("reminder list count includes retained states, excludes drafts, and stays total when states collapse", () => {
  const expanded = projectDashboardVisits(visits);
  const collapsed = projectDashboardVisits(visits, ["active", "stopping", "stopped", "expired"]);

  assert.equal(expanded.drafts.length, 1);
  assert.equal(expanded.reminderCount, 4);
  assert.deepEqual(expanded.reminders.map(({ state }) => state), ["active", "stopping", "stopped", "expired"]);
  assert.equal(collapsed.visibleReminders.length, 0);
  assert.equal(collapsed.reminderCount, 4);
});
