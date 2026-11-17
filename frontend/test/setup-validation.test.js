import test from "node:test";
import assert from "node:assert/strict";
import { validateSetup } from "../src/setup-validation.js";

const TODAY = "2026-11-10";
const roster = {
  available: true,
  reason: "ok",
  clinics: [{ session: "morning", room: "03", doctor: "合成醫師甲", clinic_type: "角膜", clinic_code: "03/合成醫師甲/角膜" }],
};

test("a clinic outside the returned clinic schedule is rejected for a date far beyond any window", () => {
  // 2027-02-01 is months ahead; the backend still returned a clinic schedule.
  const errors = validateSetup({ date: "2027-02-01", today: TODAY, clinic: "99/陌生醫師/角膜", roster });
  assert.equal(errors.clinic_code, "所選醫師該日該科沒有排班，請重新選擇。");
});

test("a clinic inside the returned clinic schedule passes", () => {
  assert.deepEqual(validateSetup({ date: "2027-02-01", today: TODAY, clinic: "03/合成醫師甲/角膜", roster }), {});
});

test("no choice is rejected when a clinic schedule was returned", () => {
  assert.equal(validateSetup({ date: "2026-11-12", today: TODAY, clinic: "", roster }).clinic_code, "請選擇醫師。");
});

test("today uses the same-day wording", () => {
  assert.equal(
    validateSetup({ date: TODAY, today: TODAY, clinic: "99/x/y", roster }).clinic_code,
    "所選醫師當天該科沒有看診，請重新選擇。",
  );
});

test("without a returned clinic schedule the clinic is not checked on the frontend", () => {
  assert.deepEqual(validateSetup({ date: "2027-02-01", today: TODAY, clinic: "anything", roster: null }), {});
  assert.deepEqual(
    validateSetup({ date: "2027-02-01", today: TODAY, clinic: "anything", roster: { available: false, reason: "visit_date_out_of_schedule_window", clinics: [] } }),
    {},
  );
});

test("a past date is still rejected", () => {
  assert.equal(
    validateSetup({ date: "2026-11-09", today: TODAY, clinic: "", roster: null }).date,
    "看診日期已過，請選擇今天或之後的日期。",
  );
});
