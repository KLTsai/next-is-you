import test from "node:test";
import assert from "node:assert/strict";
import * as setupNotices from "../src/schedule-window.js";
import {
  currentNumberOnlyNotice,
  degradeNotice,
  rosterClinicError,
  unpublishedDayNotice,
  visitErrorMessage,
} from "../src/schedule-window.js";

test("the not-yet-published notice composes catalog name, end date and release time", () => {
  const notice = unpublishedDayNotice({
    hospitalName: "臺大醫院總院",
    scheduleEnd: "2026-11-05",
    releaseTime: "2026-10-23T00:00:00+08:00",
    visitDate: "2026-11-06",
  });
  assert.equal(
    notice,
    "臺大醫院總院 目前只公布到 11/5 的門診表。11/6 的門診表預計 10/23 00:00 公布，公布後系統會自動核對你存的草稿。",
  );
});

test("the notice asks the user to confirm with the hospital when no release time is returned", () => {
  const notice = unpublishedDayNotice({
    hospitalName: "合成醫院",
    scheduleEnd: "2026-11-03",
    releaseTime: null,
    visitDate: "2026-11-20",
  });
  assert.equal(
    notice,
    "合成醫院 目前只公布到 11/3 的門診表。院方未公布這一天門診表的確切時間，請向院方確認。",
  );
});

test("the release time is shown in Taipei time whatever offset the backend writes", () => {
  const notice = unpublishedDayNotice({
    hospitalName: "臺大醫院總院",
    scheduleEnd: "2026-11-05",
    releaseTime: "2026-10-22T16:00:00+00:00",
    visitDate: "2026-11-06",
  });
  assert.ok(notice.includes("預計 10/23 00:00 公布"));
});

test("the frontend carries no clinic schedule date arithmetic or lookahead constant", () => {
  for (const name of [
    "SCHEDULE_LOOKAHEAD_DAYS",
    "addDaysISO",
    "withinScheduleWindow",
    "beyondScheduleWindow",
  ]) {
    assert.equal(name in setupNotices, false, `${name} must not be exported`);
  }
});

const ROSTER = {
  available: true,
  reason: "ok",
  clinics: [
    { clinic_code: "11/Wang/Dr. Appt.", doctor: "Wang", room: "11", session: "morning", clinic_type: "Dr. Appt." },
  ],
};

test("a clinic outside the returned clinic schedule is rejected, whatever the date", () => {
  assert.equal(rosterClinicError(ROSTER, "99/Other/Dr. Appt.", false), "所選醫師該日該科沒有排班，請重新選擇。");
  assert.equal(rosterClinicError(ROSTER, "99/Other/Dr. Appt.", true), "所選醫師當天該科沒有看診，請重新選擇。");
  assert.equal(rosterClinicError(ROSTER, "", false), "請選擇醫師。");
  assert.equal(rosterClinicError(ROSTER, "11/Wang/Dr. Appt.", false), "");
});

test("no clinic check applies when the backend returned no clinic schedule", () => {
  assert.equal(rosterClinicError(null, "anything", false), "");
  assert.equal(
    rosterClinicError({ available: false, reason: "no_observation", clinics: [] }, "anything", false),
    "",
  );
});

test("degradeNotice names each reason the roster API can return", () => {
  assert.ok(degradeNotice("visit_date_past").includes("看診日期已過"));
  assert.ok(degradeNotice("no_observation").includes("切換為手動輸入"));
  assert.ok(degradeNotice("access_denied").includes("院方暫時拒絕"));
  assert.ok(degradeNotice("timeout").includes("逾時"));
  assert.ok(degradeNotice("schema_drift").includes("格式無法辨識"));
  assert.ok(degradeNotice("scope_mismatch").includes("不在支援範圍"));
  assert.equal(degradeNotice("date_not_today"), degradeNotice("entirely-unknown-reason"));
});

test("visitErrorMessage maps the backend's Start-time error codes to user-facing text", () => {
  assert.ok(visitErrorMessage("doctor_not_scheduled").includes("並沒有看診"));
  assert.ok(visitErrorMessage("schedule_unavailable").includes("請稍後再試"));
  assert.ok(visitErrorMessage("visit_date_out_of_schedule_window").includes("尚未公布"));
  assert.ok(visitErrorMessage("visit_date_past").includes("看診日期已過"));
  assert.ok(visitErrorMessage("clinic_combo_mismatch").includes("組合"));
  assert.equal(visitErrorMessage("observation_unavailable"), "");
  assert.equal(visitErrorMessage(""), "");
});

test("a hospital with no clinic schedule explains each refused Start in plain words", () => {
  assert.equal(
    visitErrorMessage("start_on_visit_day_only", { visitDate: "2026-11-20" }),
    "這家醫院沒有公布門診表，11/20 看診當天才能開始。",
  );
  assert.equal(
    visitErrorMessage("start_on_visit_day_only", { visitDate: "2026-12-01" }),
    "這家醫院沒有公布門診表，12/1 看診當天才能開始。",
  );
  assert.equal(
    visitErrorMessage("hospital_cannot_find_clinic"),
    "院方目前查不到這個診。如果還沒開診，請開診後再試；否則請核對診間代碼。",
  );
  assert.equal(
    visitErrorMessage("hospital_page_unreachable"),
    "暫時讀不到院方資料，請稍後再試。",
  );
});

test("the visit-day refusal still reads without a date", () => {
  assert.equal(
    visitErrorMessage("start_on_visit_day_only"),
    "這家醫院沒有公布門診表，看診當天才能開始。",
  );
});

test("a hospital with no clinic schedule says so instead of blaming a failed read", () => {
  const notice = currentNumberOnlyNotice();
  assert.ok(notice.includes("沒有公布門診表"));
  assert.ok(notice.includes("看診當天才能開始"));
  assert.ok(!notice.includes("無法取得"));
});
