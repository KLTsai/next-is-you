import test from "node:test";
import assert from "node:assert/strict";
import { REFUSAL_TEXTS, startRefusalMessage, visitErrorMessage } from "../src/refusal-texts.js";
import { unpublishedDayNotice } from "../src/schedule-window.js";

test("visitErrorMessage maps the backend's Start-time error codes to user-facing text", () => {
  assert.ok(visitErrorMessage("doctor_not_scheduled").includes("並沒有看診"));
  assert.ok(visitErrorMessage("schedule_unavailable").includes("請稍後再試"));
  assert.equal(visitErrorMessage("visit_date_out_of_schedule_window"), "");
  assert.ok(visitErrorMessage("visit_date_past").includes("看診日期已過"));
  assert.ok(visitErrorMessage("clinic_combo_mismatch").includes("組合"));
  assert.equal(visitErrorMessage("observation_unavailable"), "目前沒有可用的可信院方觀察，維持草稿。");
  assert.equal(visitErrorMessage("not_a_refusal_code"), "");
  assert.equal(visitErrorMessage("toString"), "");
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
    "院方目前查不到此診。如果還沒開診，請開診後再試；否則請核對診間代碼。",
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

test("a refused Start for an unpublished day shows the same text as the setup form, with a release time", () => {
  const input = {
    hospitalName: "臺大醫院總院",
    scheduleEnd: "2026-12-01",
    releaseTime: "2026-11-21T00:00:00+08:00",
    visitDate: "2026-12-05",
  };
  const message = startRefusalMessage({ code: "visit_date_out_of_schedule_window", ...input });
  assert.equal(
    message,
    "臺大醫院總院 目前只公布到 12/1 的門診表。12/5 的門診表預計 11/21 00:00 公布，公布後系統會自動核對你存的草稿。",
  );
  assert.equal(message, unpublishedDayNotice(input));
});

test("a refused Start without a release time tells the organizer to ask the hospital", () => {
  const message = startRefusalMessage({
    code: "visit_date_out_of_schedule_window",
    hospitalName: "合成醫院",
    scheduleEnd: "2026-12-01",
    releaseTime: null,
    visitDate: "2026-12-05",
  });
  assert.equal(
    message,
    "合成醫院 目前只公布到 12/1 的門診表。院方未公布這一天門診表的確切時間，請向院方確認。",
  );
});

test("startRefusalMessage falls back to a plain notice, never the reload hint, when the facts are missing", () => {
  assert.ok(startRefusalMessage({ code: "doctor_not_scheduled" }).includes("並沒有看診"));
  assert.equal(startRefusalMessage({ code: "not_a_refusal_code" }), "");
  assert.equal(
    startRefusalMessage({ code: "visit_date_out_of_schedule_window", hospitalName: "合成醫院", visitDate: "2026-12-05" }),
    "院方還沒公布這一天的門診表，公布後再開始追蹤。",
  );
  assert.equal(
    startRefusalMessage({ code: "visit_date_out_of_schedule_window", scheduleEnd: "2026-12-01", visitDate: "2026-12-05" }),
    "院方還沒公布這一天的門診表，公布後再開始追蹤。",
  );
});

test("a refused Start for a hospital with no clinic schedule names the visit day the backend gave", () => {
  assert.equal(
    startRefusalMessage({ code: "start_on_visit_day_only", visitDate: "2026-11-20" }),
    "這家醫院沒有公布門診表，11/20 看診當天才能開始。",
  );
  assert.equal(
    startRefusalMessage({ code: "hospital_page_unreachable" }),
    "暫時讀不到院方資料，請稍後再試。",
  );
});

test("a refused Start while another visit runs tells the organizer to stop it first", () => {
  assert.equal(
    startRefusalMessage({ code: "another_visit_running" }),
    "目前已有一筆追蹤在進行中，請先停止它再開始這一筆。",
  );
});

const KNOWN_ACTIONS = new Set([
  "retry_later",
  "reload",
  "pick_recipients",
  "pick_date",
  "pick_again",
  "wait_for_schedule",
  "start_on_visit_day",
  "check_clinic_code",
  "stop_running_visit",
]);

test("every refusal text names a known action and is a string or a function of facts", () => {
  for (const [code, entry] of Object.entries(REFUSAL_TEXTS)) {
    assert.ok(KNOWN_ACTIONS.has(entry.action), `${code} has unknown action ${entry.action}`);
    assert.ok(typeof entry.text === "string" || typeof entry.text === "function", code);
  }
});
