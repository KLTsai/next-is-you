// Setup-form notices and pre-submit checks that depend on the clinic schedule
// the backend returned. The frontend never computes which days a hospital has
// published: it renders the end date and release time the backend states, and
// checks a chosen clinic against the clinic schedule it was given.

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})/;

// "2026-11-05" -> "11/5". Reads the date as written; no calendar arithmetic.
function monthDay(iso) {
  const match = ISO_DATE.exec(String(iso ?? ""));
  return match ? `${Number(match[2])}/${Number(match[3])}` : "";
}

// An ISO timestamp -> "10/23 00:00" in Taipei time.
function taipeiMonthDayTime(iso) {
  const moment = new Date(iso);
  if (Number.isNaN(moment.getTime())) return "";
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-GB", {
      timeZone: "Asia/Taipei",
      month: "numeric",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    })
      .formatToParts(moment)
      .map((part) => [part.type, part.value]),
  );
  return `${parts.month}/${parts.day} ${parts.hour}:${parts.minute}`;
}

export function unpublishedDayNotice({ hospitalName, scheduleEnd, releaseTime, visitDate }) {
  const published = `${hospitalName} 目前只公布到 ${monthDay(scheduleEnd)} 的門診表。`;
  const release = releaseTime ? taipeiMonthDayTime(releaseTime) : "";
  if (!release) return `${published}院方未公布這一天門診表的確切時間，請向院方確認。`;
  return `${published}${monthDay(visitDate)} 的門診表預計 ${release} 公布，公布後系統會自動核對你存的草稿。`;
}

// The error for a chosen clinic that is not in the clinic schedule the backend
// returned, or "" when it is in it or no clinic schedule was returned.
export function rosterClinicError(roster, clinic, isToday) {
  if (!roster || !roster.available) return "";
  if (!clinic) return "請選擇醫師。";
  if (roster.clinics.some((option) => option.clinic_code === clinic)) return "";
  return isToday
    ? "所選醫師當天該科沒有看診，請重新選擇。"
    : "所選醫師該日該科沒有排班，請重新選擇。";
}

const DEGRADE_MESSAGES = Object.freeze({
  no_observation: "目前無法取得當日門診名單（服務尚未開放即時讀取），已切換為手動輸入。",
  access_denied: "院方暫時拒絕讀取當日名單，已切換為手動輸入。",
  timeout: "讀取院方名單逾時，已切換為手動輸入。",
  schema_drift: "院方頁面格式無法辨識，已切換為手動輸入。",
  scope_mismatch: "此科別不在支援範圍，已切換為手動輸入。",
  visit_date_past: "看診日期已過，請選擇今天或之後的日期。",
});

export function degradeNotice(reason) {
  return DEGRADE_MESSAGES[reason] ?? "目前無法取得門診名單，已切換為手動輸入。";
}

// Shown above manual entry for a hospital that publishes no clinic schedule:
// nothing failed, there is simply no clinic schedule to pick from.
export function currentNumberOnlyNotice() {
  return "這家醫院沒有公布門診表，請照院方進度頁上的診間資料手動輸入。草稿隨時可以儲存，看診當天才能開始提醒。";
}

const VISIT_ERROR_MESSAGES = Object.freeze({
  visit_date_past: "看診日期已過，請選擇今天或之後的日期。",
  doctor_not_scheduled: "所選醫師在那天並沒有看診，請重新選擇醫師或日期。",
  clinic_combo_mismatch: "科別、醫師與診間的組合與院方資料不符，請重新選擇。",
  schedule_unavailable: "暫時無法驗證醫師排班（院方頁回應異常），請稍後再試。",
});

// Start refusals for a hospital that publishes no clinic schedule. The backend
// decides which one applies; the frontend only words it.
function visitDayOnlyMessage(visitDate) {
  const match = /^\d{4}-(\d{2})-(\d{2})$/.exec(visitDate ?? "");
  const day = match ? `${Number(match[1])}/${Number(match[2])} ` : "";
  return `這家醫院沒有公布門診表，${day}看診當天才能開始。`;
}

const CURRENT_NUMBER_ONLY_MESSAGES = Object.freeze({
  hospital_cannot_find_clinic: "院方目前查不到這個診。如果還沒開診，請開診後再試；否則請核對診間代碼。",
  hospital_page_unreachable: "暫時讀不到院方資料，請稍後再試。",
});

export function visitErrorMessage(code, { visitDate } = {}) {
  if (code === "start_on_visit_day_only") return visitDayOnlyMessage(visitDate);
  return CURRENT_NUMBER_ONLY_MESSAGES[code] ?? VISIT_ERROR_MESSAGES[code] ?? "";
}

// Used when the refusal lacks the hospital name or end date to compose the full
// notice (catalog not loaded, hospital retired): reloading would not help, so
// say what is true without them.
const UNPUBLISHED_DAY_FALLBACK = "院方還沒公布這一天的門診表，公布後再開始提醒。";

// The text for a refused Start. A not-yet-published day reuses the setup form's
// notice, or a hospital-free fallback when its facts are missing; any other code
// uses the generic Start error text, and "" means the caller has no specific
// text for it.
export function startRefusalMessage({ code, hospitalName, scheduleEnd, releaseTime, visitDate }) {
  if (code === "visit_date_out_of_schedule_window") {
    if (!scheduleEnd || !hospitalName) return UNPUBLISHED_DAY_FALLBACK;
    return unpublishedDayNotice({ hospitalName, scheduleEnd, releaseTime, visitDate });
  }
  return visitErrorMessage(code, { visitDate });
}
