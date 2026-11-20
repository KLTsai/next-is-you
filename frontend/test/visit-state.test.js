import test from "node:test";
import assert from "node:assert/strict";
import { canRequestStart, formatSourceStatus, formatVisitState, sendInterruptionNotice, visitStatusKey } from "../src/visit-state.js";

const visit = {
  id: "synthetic-visit",
  hospital: "ntuh-main",
  date: "2026-09-28",
  department_code: "MED",
  clinic_code: "MED-101",
  session: "afternoon",
  state: "draft",
  observation: { current_number: null, checked_at: null },
  source_read: { status: "usable", reason: "none" },
  notification: { count: 0, accepted: 0, issues: 0 },
  recipients: [{ id: "synthetic-recipient", display_name: "Family" }],
};

test("Start can only be requested for a complete draft and a selected recipient", () => {
  assert.equal(canRequestStart(visit), true);
  assert.equal(canRequestStart({ ...visit, source_read: { status: "unavailable", reason: "no_observation" } }), true);
  assert.equal(canRequestStart({ ...visit, recipients: [] }), false);
  assert.equal(canRequestStart({ ...visit, clinic_code: "" }), false);
  assert.equal(canRequestStart({ ...visit, state: "active" }), false);
});

test("source availability and lifecycle state remain distinct in the UI", () => {
  assert.equal(visitStatusKey({ ...visit, state: "draft", source_read: { status: "unavailable" } }), "source-unavailable");
  assert.equal(visitStatusKey({ ...visit, state: "draft", source_read: { status: "usable" } }), "draft");
  assert.equal(visitStatusKey({ ...visit, state: "expired" }), "terminal");
  assert.deepEqual(["draft", "active", "stopping", "stopped", "expired"].map(formatVisitState), ["草稿", "監控中", "停止中", "已停止", "已結束"]);
  assert.deepEqual(["usable", "unavailable", "stale", "untrusted", "scope_mismatch", "invalid"].map(formatSourceStatus), ["資料已核對", "來源暫不可用", "資料已過期", "來源尚未驗證", "診次資料不相符", "資料格式無效"]);
});

test("a running visit says reminders are paused only while sending is interrupted", () => {
  const running = { ...visit, state: "active" };
  assert.equal(sendInterruptionNotice(running, true), "發送中斷中，提醒暫停");
  assert.equal(sendInterruptionNotice(running, false), null);
  for (const state of ["draft", "stopping", "stopped", "expired"]) {
    assert.equal(sendInterruptionNotice({ ...visit, state }, true), null, state);
  }
});
