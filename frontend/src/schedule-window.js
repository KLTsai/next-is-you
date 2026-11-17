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

const VISIT_ERROR_MESSAGES = Object.freeze({
  visit_date_past: "看診日期已過，請選擇今天或之後的日期。",
  doctor_not_scheduled: "所選醫師在那天並沒有看診，請重新選擇醫師或日期。",
  clinic_combo_mismatch: "科別、醫師與診間的組合與院方資料不符，請重新選擇。",
  schedule_unavailable: "暫時無法驗證醫師排班（院方頁回應異常），請稍後再試。",
});

export function visitErrorMessage(code) {
  return VISIT_ERROR_MESSAGES[code] ?? "";
}

// The text for a refused Start. A not-yet-published day reuses the setup form's
// notice; any other code uses the generic Start error text, and "" means the
// caller has no specific text for it.
export function startRefusalMessage({ code, hospitalName, scheduleEnd, releaseTime, visitDate }) {
  if (code === "visit_date_out_of_schedule_window") {
    if (!scheduleEnd || !hospitalName) return "";
    return unpublishedDayNotice({ hospitalName, scheduleEnd, releaseTime, visitDate });
  }
  return visitErrorMessage(code);
}
