import test from "node:test";
import assert from "node:assert/strict";
import * as setupNotices from "../src/schedule-window.js";
import {
  currentNumberOnlyNotice,
  degradeNotice,
  rosterClinicError,
  unpublishedDayNotice,
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

test("a hospital with no clinic schedule says so instead of blaming a failed read", () => {
  const notice = currentNumberOnlyNotice();
  assert.ok(notice.includes("沒有公布門診表"));
  assert.ok(notice.includes("看診當天才能開始"));
  assert.ok(!notice.includes("無法取得"));
});

test("no frontend text names NTUH or a two-week window", async () => {
  const { readdir, readFile } = await import("node:fs/promises");
  const dir = new URL("../src/", import.meta.url);
  for (const name of await readdir(dir)) {
    if (!/\.(js|ts)$/.test(name)) continue;
    const text = await readFile(new URL(name, dir), "utf8");
    assert.doesNotMatch(text, /NTUH|兩週|兩周|[Tt]wo[- ]week/, name);
  }
});
