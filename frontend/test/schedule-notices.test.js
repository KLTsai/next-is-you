import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  degradeNotice,
  formatMonthDay,
  formatReleaseTime,
  notYetPublishedNotice,
  startRefusalMessage,
  visitErrorMessage,
} from "../src/schedule-notices.js";

test("the notice with a stated release time is composed from catalog name, end date and release time", () => {
  assert.equal(
    notYetPublishedNotice({
      hospitalName: "臺大醫院總院",
      endDate: "2026-12-01",
      visitDate: "2026-12-05",
      releaseTime: "2026-11-21T00:00:00+08:00",
    }),
    "臺大醫院總院 目前只公布到 12/1 的門診表。12/5 的門診表預計 11/21 00:00 公布，公布後系統會自動核對你存的草稿。",
  );
});

test("the notice without a release time says the hospital did not state one", () => {
  const expected = "合成醫院（僅供測試） 目前只公布到 12/1 的門診表。院方未公布這一天門診表的確切時間，請向院方確認。";
  for (const releaseTime of [null, undefined, ""]) {
    assert.equal(
      notYetPublishedNotice({
        hospitalName: "合成醫院（僅供測試）",
        endDate: "2026-12-01",
        visitDate: "2026-12-05",
        releaseTime,
      }),
      expected,
    );
  }
});

test("the release time is shown in Taipei time whatever offset the backend used", () => {
  assert.equal(formatReleaseTime("2026-11-20T16:00:00Z"), "11/21 00:00");
  assert.equal(formatReleaseTime("2026-11-21T08:30:00+08:00"), "11/21 08:30");
  assert.equal(formatReleaseTime("not a time"), "");
  assert.equal(formatReleaseTime(null), "");
});

test("month and day are written without zero padding", () => {
  assert.equal(formatMonthDay("2026-01-05"), "1/5");
  assert.equal(formatMonthDay("2026-12-31"), "12/31");
  assert.equal(formatMonthDay("nope"), "");
});

test("degradeNotice names each reason the clinic schedule answer can return", () => {
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
  assert.ok(visitErrorMessage("visit_date_past").includes("看診日期已過"));
  assert.ok(visitErrorMessage("clinic_combo_mismatch").includes("組合"));
  // The unpublished-day refusal is worded by startRefusalMessage, not here.
  assert.equal(visitErrorMessage("visit_date_out_of_schedule_window"), "");
  assert.equal(visitErrorMessage("observation_unavailable"), "");
  assert.equal(visitErrorMessage(""), "");
});

test("the setup page source holds no clinic schedule date arithmetic or lookahead constant", () => {
  for (const file of ["main.ts", "schedule-notices.js"]) {
    const source = readFileSync(new URL(`../src/${file}`, import.meta.url), "utf8");
    assert.ok(!/LOOKAHEAD|addDaysISO|withinScheduleWindow|beyondScheduleWindow/i.test(source), file);
    assert.ok(!/setUTCDate|setDate\(|getDate\(\)\s*[+-]/.test(source), file);
  }
});

test("a refused Start for an unpublished day reuses the setup form's two notices", () => {
  const base = { code: "visit_date_out_of_schedule_window", hospitalName: "臺大醫院總院", visitDate: "2026-12-05" };
  assert.equal(
    startRefusalMessage({ ...base, details: { schedule_end_date: "2026-12-01", release_time: "2026-11-21T00:00:00+08:00" } }),
    "臺大醫院總院 目前只公布到 12/1 的門診表。12/5 的門診表預計 11/21 00:00 公布，公布後系統會自動核對你存的草稿。",
  );
  assert.equal(
    startRefusalMessage({ ...base, details: { schedule_end_date: "2026-12-01", release_time: null } }),
    "臺大醫院總院 目前只公布到 12/1 的門診表。院方未公布這一天門診表的確切時間，請向院方確認。",
  );
});

test("a refused Start without the backend's end date still names no window length", () => {
  const text = startRefusalMessage({ code: "visit_date_out_of_schedule_window", details: {}, hospitalName: "某醫院", visitDate: "2026-12-05" });
  assert.ok(text.startsWith("某醫院 "));
  assert.ok(!/NTUH|兩週/.test(text));
});

test("other refused Start codes keep their fixed texts", () => {
  assert.ok(startRefusalMessage({ code: "doctor_not_scheduled", details: {}, hospitalName: "x", visitDate: "" }).includes("並沒有看診"));
  assert.equal(startRefusalMessage({ code: "observation_unavailable", details: {}, hospitalName: "x", visitDate: "" }), "");
});
