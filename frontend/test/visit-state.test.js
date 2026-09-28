import test from "node:test";
import assert from "node:assert/strict";
import { canStartVisit, formatStatus, isFreshMatchingObservation, VISIT_STATUSES } from "../src/visit-state.js";

const now = Date.parse("2026-09-28T03:00:00Z");
const visit = {
  status: "draft",
  hospital: "ntuh-main",
  visitDate: "2026-09-28",
  departmentCode: "synthetic-department",
  clinicCode: "synthetic-clinic",
  session: "afternoon",
  recipients: ["synthetic-recipient"],
  observation: {
    hospital: "ntuh-main",
    visitDate: "2026-09-28",
    departmentCode: "synthetic-department",
    clinicCode: "synthetic-clinic",
    session: "afternoon",
    trustworthy: true,
    observedAt: "2026-09-28T02:59:00Z",
    currentNumber: 21,
    nextNumber: 20,
    callType: "regular",
  },
};

test("start requires a fresh trusted exact-scope observation and an eligible recipient", () => {
  assert.equal(canStartVisit(visit, now), true);
  assert.equal(canStartVisit({ ...visit, observation: { ...visit.observation, trustworthy: false } }, now), false);
  assert.equal(canStartVisit({ ...visit, observation: { ...visit.observation, clinicCode: "other-clinic" } }, now), false);
  assert.equal(canStartVisit({ ...visit, observation: { ...visit.observation, currentNumber: 0 } }, now), false);
  assert.equal(canStartVisit({ ...visit, observation: { ...visit.observation, observedAt: "2026-09-28T02:57:59Z" } }, now), false);
  assert.equal(canStartVisit({ ...visit, recipients: [] }, now), false);
  assert.equal(canStartVisit({ ...visit, status: "active" }, now), false);
});

test("a scope without a selected clinic and session cannot match", () => {
  assert.equal(isFreshMatchingObservation(visit.observation, { ...visit, clinicCode: null }, now), false);
  assert.equal(isFreshMatchingObservation(visit.observation, { ...visit, session: null }, now), false);
});

test("all lifecycle states have distinct user-facing labels", () => {
  assert.deepEqual(VISIT_STATUSES.map(formatStatus), ["草稿", "監控中", "停止中", "已停止", "來源 unavailable", "已結束"]);
  assert.equal(new Set(VISIT_STATUSES.map(formatStatus)).size, VISIT_STATUSES.length);
});
