import test from "node:test";
import assert from "node:assert/strict";
import {
  SCHEDULE_LOOKAHEAD_DAYS,
  addDaysISO,
  beyondScheduleWindow,
  degradeNotice,
  visitErrorMessage,
  withinScheduleWindow,
} from "../src/schedule-window.js";

const TODAY = "2026-11-10";

test("the schedule window is 14 days ahead of today, matching NTUH's lookahead", () => {
  assert.equal(SCHEDULE_LOOKAHEAD_DAYS, 14);
  assert.equal(addDaysISO(TODAY, 0), TODAY);
  assert.equal(addDaysISO(TODAY, 1), "2026-11-11");
  assert.equal(addDaysISO(TODAY, SCHEDULE_LOOKAHEAD_DAYS), "2026-11-24");
  assert.equal(addDaysISO(TODAY, 21), "2026-12-01"); // crosses a month boundary
  assert.equal(addDaysISO("2026-12-25", 10), "2027-01-04"); // crosses a year boundary
  assert.equal(addDaysISO("not-a-date", 1), "");
});

test("the roster-fetch gate accepts today through today+14 and refuses everything else", () => {
  assert.equal(withinScheduleWindow(TODAY, TODAY), true);
  assert.equal(withinScheduleWindow("2026-11-11", TODAY), true);
  assert.equal(withinScheduleWindow("2026-11-24", TODAY), true); // today + 14
  assert.equal(withinScheduleWindow("2026-11-25", TODAY), false); // today + 15
  assert.equal(withinScheduleWindow("2026-11-09", TODAY), false); // yesterday
  assert.equal(withinScheduleWindow("", TODAY), false);
  assert.equal(withinScheduleWindow(TODAY, ""), false);
});

test("beyondScheduleWindow only fires for dates strictly past today+14, not for past dates", () => {
  assert.equal(beyondScheduleWindow("2026-11-25", TODAY), true);
  assert.equal(beyondScheduleWindow("2026-12-15", TODAY), true);
  assert.equal(beyondScheduleWindow("2026-11-24", TODAY), false);
  assert.equal(beyondScheduleWindow(TODAY, TODAY), false);
  // A past date is handled by the visit_date_past branch, not by this gate.
  assert.equal(beyondScheduleWindow("2026-11-09", TODAY), false);
});

test("degradeNotice names each reason the roster API can return, including the new window and past-date entries", () => {
  assert.ok(degradeNotice("visit_date_out_of_schedule_window").includes("兩週掛號視窗"));
  assert.ok(degradeNotice("visit_date_past").includes("看診日期已過"));
  assert.ok(degradeNotice("no_observation").includes("切換為手動輸入"));
  assert.ok(degradeNotice("access_denied").includes("院方暫時拒絕"));
  assert.ok(degradeNotice("timeout").includes("逾時"));
  assert.ok(degradeNotice("schema_drift").includes("格式無法辨識"));
  assert.ok(degradeNotice("scope_mismatch").includes("不在支援範圍"));
  // date_not_today is retired; an unknown reason still falls back to a safe default.
  assert.equal(typeof degradeNotice("date_not_today"), "string");
  assert.ok(degradeNotice("date_not_today").length > 0);
  assert.equal(
    degradeNotice("date_not_today"),
    degradeNotice("entirely-unknown-reason"),
    "retired reasons fall through to the default string",
  );
});

test("visitErrorMessage maps the backend's new Start-time error codes to user-facing text", () => {
  assert.ok(visitErrorMessage("doctor_not_scheduled").includes("並沒有看診"));
  assert.ok(visitErrorMessage("schedule_unavailable").includes("請稍後再試"));
  assert.ok(visitErrorMessage("visit_date_out_of_schedule_window").includes("兩週掛號視窗"));
  assert.ok(visitErrorMessage("visit_date_past").includes("看診日期已過"));
  assert.ok(visitErrorMessage("clinic_combo_mismatch").includes("組合"));
  // Codes outside the pre-flight set return "" so the main errorText fallback
  // chain can keep handling them.
  assert.equal(visitErrorMessage("observation_unavailable"), "");
  assert.equal(visitErrorMessage(""), "");
});
