import test from "node:test";
import assert from "node:assert/strict";
import { clinicCodePreview, hasUnsavedChanges, setupFormErrors } from "../src/setup-form.js";

const PAST = "看診日期已過，請選擇今天或之後的日期。";
const TODAY = "2026-11-18";
const KEY = "h\u0000d1\u00002026-11-18";

const roster = (codes, available = true) => ({
  available,
  clinics: codes.map((clinic_code) => ({ clinic_code })),
});

function errors(overrides = {}) {
  return setupFormErrors({
    date: TODAY,
    clinic: "",
    today: TODAY,
    fullSchedule: false,
    roster: null,
    rosterKey: "",
    selectionKey: KEY,
    ...overrides,
  });
}

test("a visit date before today is an error, today and later are allowed", () => {
  assert.deepEqual(errors({ date: "2026-11-17" }), { date: PAST });
  assert.deepEqual(errors({ date: "2026-11-18" }), {});
  assert.deepEqual(errors({ date: "2026-11-19" }), {});
});

test("an empty date adds no date error", () => {
  assert.deepEqual(errors({ date: "" }), {});
});

test("a clinic outside the returned clinic schedule is an error for the same selection", () => {
  const result = errors({
    fullSchedule: true,
    roster: roster(["A1"]),
    rosterKey: KEY,
    clinic: "ZZ",
    date: TODAY,
  });
  assert.equal(result.clinic_code, "所選醫師當天該科沒有看診，請重新選擇。");
});

test("a clinic inside the returned clinic schedule is accepted", () => {
  const result = errors({ fullSchedule: true, roster: roster(["A1"]), rosterKey: KEY, clinic: "A1" });
  assert.deepEqual(result, {});
});

test("a clinic schedule for another hospital, department or date is not used", () => {
  const result = errors({
    fullSchedule: true,
    roster: roster(["A1"]),
    rosterKey: "h\u0000d2\u00002026-11-18",
    clinic: "ZZ",
  });
  assert.deepEqual(result, {});
});

test("an unavailable clinic schedule adds no clinic check", () => {
  const result = errors({ fullSchedule: true, roster: roster([], false), rosterKey: KEY, clinic: "ZZ" });
  assert.deepEqual(result, {});
});

test("a hospital without a full schedule never gets a clinic check (manual entry)", () => {
  const result = errors({ fullSchedule: false, roster: roster(["A1"]), rosterKey: KEY, clinic: "ZZ" });
  assert.deepEqual(result, {});
});

test("a past date and a wrong clinic are both reported", () => {
  const result = errors({
    date: "2026-11-17",
    fullSchedule: true,
    roster: roster(["A1"]),
    rosterKey: "h\u0000d1\u00002026-11-17",
    selectionKey: "h\u0000d1\u00002026-11-17",
    clinic: "ZZ",
  });
  assert.equal(result.date, PAST);
  assert.equal(result.clinic_code, "所選醫師該日該科沒有排班，請重新選擇。");
});

const LABELS = ["診間", "診別"];

test("empty input shows no preview", () => {
  assert.deepEqual(clinicCodePreview(LABELS, ""), { cls: "", html: "" });
});

test("no labels shows no preview", () => {
  assert.deepEqual(clinicCodePreview([], "12/34"), { cls: "", html: "" });
});

test("a code with as many non-empty parts as labels shows the labelled read", () => {
  const { cls, html } = clinicCodePreview(LABELS, " 12 / 34 ");
  assert.equal(cls, "");
  assert.equal(html, '系統讀到：診間 <b>12</b>｜診別 <b>34</b> <span class="ok">✓</span>');
});

test("too few or too many parts show the format hint built from the labels", () => {
  const hint = { cls: "warn", html: "格式通常為「診間/診別」，請對照院方進度頁。" };
  assert.deepEqual(clinicCodePreview(LABELS, "12"), hint);
  assert.deepEqual(clinicCodePreview(LABELS, "12/34/56"), hint);
});

test("an empty part shows the format hint", () => {
  const hint = { cls: "warn", html: "格式通常為「診間/診別」，請對照院方進度頁。" };
  assert.deepEqual(clinicCodePreview(LABELS, "12/"), hint);
  assert.deepEqual(clinicCodePreview(LABELS, "12/ "), hint);
});

test("the preview escapes labels and parts", () => {
  const { html } = clinicCodePreview(["<a>"], "<b>");
  assert.equal(html, '系統讀到：&lt;a&gt; <b>&lt;b&gt;</b> <span class="ok">✓</span>');
});

const SAVED = {
  hospital: "h",
  date: "2026-11-18",
  department_code: "d1",
  clinic_code: "A1",
  session: "afternoon",
  recipients: [{ id: "r2" }, { id: "r1" }],
};

function unsaved(overrides = {}) {
  return hasUnsavedChanges({
    current: {},
    saved: undefined,
    firstHospital: "h",
    firstDepartmentOf: (hospital) => (hospital === "h" ? "d1" : "x1"),
    initialPatientNumber: undefined,
    ...overrides,
  });
}

const SAVED_FIELDS = {
  hospital: "h",
  date: "2026-11-18",
  department_code: "d1",
  clinic_code: "A1",
  session: "afternoon",
  recipient_ids: ["r1", "r2"],
};

test("a form identical to the saved draft has no changes", () => {
  assert.equal(unsaved({ saved: SAVED, current: SAVED_FIELDS }), false);
});

test("a new draft with only the automatic defaults has no changes", () => {
  assert.equal(
    unsaved({
      current: { hospital: "h", department_code: "d1", date: "", clinic_code: "", session: "", recipient_ids: [] },
    }),
    false,
  );
});

test("the default department follows the selected hospital", () => {
  const base = { firstHospital: "g", firstDepartmentOf: (hospital) => (hospital === "g" ? "x1" : "d1") };
  assert.equal(unsaved({ ...base, current: { hospital: "g", department_code: "x1" } }), false);
  assert.equal(unsaved({ ...base, current: { hospital: "g", department_code: "x2" } }), true);
});

test("a changed field is an edit", () => {
  for (const [name, value] of [
    ["date", "2026-11-19"],
    ["department_code", "d2"],
    ["clinic_code", "B2"],
    ["session", "morning"],
    ["hospital", "g"],
  ]) {
    assert.equal(unsaved({ saved: SAVED, current: { ...SAVED_FIELDS, [name]: value } }), true, name);
  }
});

test("recipients in a different order are not an edit", () => {
  assert.equal(unsaved({ saved: SAVED, current: { ...SAVED_FIELDS, recipient_ids: ["r2", "r1"] } }), false);
});

test("a different recipient set is an edit", () => {
  assert.equal(unsaved({ saved: SAVED, current: { ...SAVED_FIELDS, recipient_ids: ["r1"] } }), true);
  assert.equal(unsaved({ current: { recipient_ids: ["r1"] } }), true);
});

test("an empty derived session is not an edit, a different one is", () => {
  assert.equal(unsaved({ saved: SAVED, current: { ...SAVED_FIELDS, session: "" } }), false);
  assert.equal(unsaved({ current: { session: "morning" } }), false);
  assert.equal(unsaved({ current: { session: "evening" } }), true);
});

test("a field absent from the form is not an edit", () => {
  const { clinic_code: _clinic, session: _session, ...visible } = SAVED_FIELDS;
  assert.equal(unsaved({ saved: SAVED, current: visible }), false);
});

test("the patient number is compared with the initial one", () => {
  assert.equal(unsaved({ current: { patient_number: "" }, initialPatientNumber: undefined }), false);
  assert.equal(unsaved({ current: { patient_number: "12" }, initialPatientNumber: "12" }), false);
  assert.equal(unsaved({ current: { patient_number: "13" }, initialPatientNumber: "12" }), true);
});

test("a hidden recipient list is not an edit, even when the saved draft has recipients", () => {
  const { recipient_ids: _recipients, ...visible } = SAVED_FIELDS;
  assert.equal(unsaved({ saved: SAVED, current: visible }), false);
});
