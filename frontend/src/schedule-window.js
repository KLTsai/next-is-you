// Shared schedule-window helpers for the setup picker: a visit date within
// `today..today+SCHEDULE_LOOKAHEAD_DAYS` can be pre-flight validated against
// the hospital's roster, and the degrade/error maps are the single place that
// names user-facing text for the five pre-flight failure classes.

export const SCHEDULE_LOOKAHEAD_DAYS = 14;

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

export function addDaysISO(iso, days) {
  if (!ISO_DATE.test(iso)) return "";
  const [year, month, day] = iso.split("-").map(Number);
  const base = new Date(Date.UTC(year, month - 1, day));
  base.setUTCDate(base.getUTCDate() + days);
  return base.toISOString().slice(0, 10);
}

export function withinScheduleWindow(date, today, lookahead = SCHEDULE_LOOKAHEAD_DAYS) {
  if (!ISO_DATE.test(date) || !ISO_DATE.test(today)) return false;
  if (date < today) return false;
  const limit = addDaysISO(today, lookahead);
  return Boolean(limit) && date <= limit;
}

export function beyondScheduleWindow(date, today, lookahead = SCHEDULE_LOOKAHEAD_DAYS) {
  if (!ISO_DATE.test(date) || !ISO_DATE.test(today)) return false;
  if (date < today) return false;
  const limit = addDaysISO(today, lookahead);
  return Boolean(limit) && date > limit;
}

const DEGRADE_MESSAGES = Object.freeze({
  no_observation: "目前無法取得當日門診名單（服務尚未開放即時讀取），已切換為手動輸入。",
  access_denied: "院方暫時拒絕讀取當日名單，已切換為手動輸入。",
  timeout: "讀取院方名單逾時，已切換為手動輸入。",
  schema_drift: "院方頁面格式無法辨識，已切換為手動輸入。",
  scope_mismatch: "此科別不在支援範圍，已切換為手動輸入。",
  visit_date_out_of_schedule_window: "此日期超過 NTUH 兩週掛號視窗，暫時改用手動輸入；系統會在日期進入視窗後重新驗證醫師排班。",
  visit_date_past: "看診日期已過，請選擇今天或之後的日期。",
});

export function degradeNotice(reason) {
  return DEGRADE_MESSAGES[reason] ?? "目前無法取得門診名單，已切換為手動輸入。";
}

const VISIT_ERROR_MESSAGES = Object.freeze({
  visit_date_past: "看診日期已過，請選擇今天或之後的日期。",
  doctor_not_scheduled: "所選醫師在那天並沒有看診，請重新選擇醫師或日期。",
  clinic_combo_mismatch: "科別、醫師與診間的組合與院方資料不符，請重新選擇。",
  schedule_unavailable: "暫時無法驗證醫師排班（院方頁回應異常），請稍後再試。",
  visit_date_out_of_schedule_window: "此日期超過 NTUH 兩週掛號視窗，暫時改用手動輸入；系統會在日期進入視窗後重新驗證醫師排班。",
});

export function visitErrorMessage(code) {
  return VISIT_ERROR_MESSAGES[code] ?? "";
}
