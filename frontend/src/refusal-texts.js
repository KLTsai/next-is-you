// The one map from a backend refusal code to the text the organizer reads and
// the action it suggests. It is keyed by the codes in the backend catalog
// (`src/next_is_you/refusal_catalog.py`); `tests/test_refusal_catalog.py` fails
// when either side has a code the other lacks.
//
// `text` is a string, or a function of the facts the refusal carries that
// returns "" while those facts are missing. `action` names what the organizer
// should do next; it is not shown yet (the draft card's link to the running visit keys off the code `another_visit_running`).

import { unpublishedDayNotice } from "./schedule-window.js";

// Shown for a not-yet-published day when the refusal lacks the hospital name or
// end date to compose the full notice (catalog not loaded, hospital retired):
// reloading would not help, so say what is true without them.
const UNPUBLISHED_DAY_FALLBACK = "院方還沒公布這一天的門診表，公布後再開始提醒。";

// Start refusal for a hospital that publishes no clinic schedule. The backend
// decides which one applies; the frontend only words it.
function visitDayOnlyText({ visitDate } = {}) {
  const match = /^\d{4}-(\d{2})-(\d{2})$/.exec(visitDate ?? "");
  const day = match ? `${Number(match[1])}/${Number(match[2])} ` : "";
  return `這家醫院沒有公布門診表，${day}看診當天才能開始。`;
}

function unpublishedDayText({ hospitalName, scheduleEnd, releaseTime, visitDate } = {}) {
  if (!scheduleEnd || !hospitalName) return "";
  return unpublishedDayNotice({ hospitalName, scheduleEnd, releaseTime, visitDate });
}

export const REFUSAL_TEXTS = Object.freeze({
  service_unavailable: { text: "目前無法使用提醒服務。", action: "retry_later" },
  visit_not_found: { text: "找不到這筆提醒，請重新載入。", action: "reload" },
  invalid_lifecycle_state: { text: "提醒狀態已變更，請重新載入。", action: "reload" },
  another_visit_running: {
    text: "目前已有一個看診在監控中，請先停止它再開始這一個。",
    action: "stop_running_visit",
  },
  ineligible_recipients: {
    text: "通知對象已無法接收提醒，請重新選擇。",
    action: "pick_recipients",
  },
  scheduler_held: { text: "排程暫停中，提醒維持草稿。", action: "retry_later" },
  observation_unavailable: {
    text: "目前沒有可用的可信院方觀察，提醒維持草稿。",
    action: "retry_later",
  },
  observation_stale: { text: "院方觀察已過期，提醒維持草稿。", action: "retry_later" },
  observation_scope_mismatch: {
    text: "院方觀察與所選診次不符，提醒維持草稿。",
    action: "retry_later",
  },
  observation_untrusted: {
    text: "院方資料尚未通過可信度檢查，提醒維持草稿。",
    action: "retry_later",
  },
  observation_invalid: { text: "院方資料無效，提醒維持草稿。", action: "retry_later" },
  clinic_ambiguous: {
    text: "院方今天有多個門診符合，系統不猜，不會發提醒。請重新選擇門診。",
    action: "pick_again",
  },
  visit_date_past: { text: "看診日期已過，請選擇今天或之後的日期。", action: "pick_date" },
  doctor_not_scheduled: {
    text: "所選醫師在那天並沒有看診，請重新選擇醫師或日期。",
    action: "pick_again",
  },
  // No backend code reaches this text yet; #149 makes it real or removes it.
  clinic_combo_mismatch: {
    text: "科別、醫師與診間的組合與院方資料不符，請重新選擇。",
    action: "pick_again",
  },
  schedule_unavailable: {
    text: "暫時無法驗證醫師排班（院方頁回應異常），請稍後再試。",
    action: "retry_later",
  },
  visit_date_out_of_schedule_window: { text: unpublishedDayText, action: "wait_for_schedule" },
  start_on_visit_day_only: { text: visitDayOnlyText, action: "start_on_visit_day" },
  hospital_cannot_find_clinic: {
    text: "院方目前查不到這個診。如果還沒開診，請開診後再試；否則請核對診間代碼。",
    action: "check_clinic_code",
  },
  hospital_page_unreachable: {
    text: "暫時讀不到院方資料，請稍後再試。",
    action: "retry_later",
  },
});

// The text for a code, or "" when the code has none or its facts are missing.
export function visitErrorMessage(code, facts = {}) {
  const entry = Object.prototype.hasOwnProperty.call(REFUSAL_TEXTS, code)
    ? REFUSAL_TEXTS[code]
    : undefined;
  if (!entry) return "";
  return typeof entry.text === "function" ? entry.text(facts) : entry.text;
}

// The text for a refused Start. A not-yet-published day uses a hospital-free
// fallback when its facts are missing; any other code uses its map text, and ""
// means the caller has no specific text for it.
export function startRefusalMessage({ code, ...facts }) {
  const message = visitErrorMessage(code, facts);
  if (message === "" && code === "visit_date_out_of_schedule_window") {
    return UNPUBLISHED_DAY_FALLBACK;
  }
  return message;
}
