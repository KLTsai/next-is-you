// User-facing text for the setup picker's clinic schedule answers. The frontend
// holds no clinic schedule rule: whether a day is published, the clinic
// schedule end date and the release time all come from the backend, and this
// module only words them.

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

// "2026-12-01" -> "12/1" (月/日). Empty for anything that is not a plain date.
export function formatMonthDay(isoDate) {
  const match = ISO_DATE.exec(isoDate ?? "");
  if (!match) return "";
  return `${Number(match[2])}/${Number(match[3])}`;
}

// An ISO timestamp -> "11/21 00:00" in Taipei time. Empty when unparseable.
export function formatReleaseTime(isoTimestamp) {
  if (!isoTimestamp) return "";
  const moment = new Date(isoTimestamp);
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

// The notice for a visit date the hospital has not published yet, composed from
// the catalog's hospital name and the backend's end date and release time.
export function notYetPublishedNotice({ hospitalName, endDate, visitDate, releaseTime }) {
  const published = `${hospitalName} 目前只公布到 ${formatMonthDay(endDate)} 的門診表。`;
  const release = formatReleaseTime(releaseTime);
  if (!release) {
    return `${published}院方未公布這一天門診表的確切時間，請向院方確認。`;
  }
  return `${published}${formatMonthDay(visitDate)} 的門診表預計 ${release} 公布，公布後系統會自動核對你存的草稿。`;
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

// The organizer's text for a refused Start. A not-yet-published day reuses the
// setup form's notice, built from the facts the backend sent with the refusal;
// every other code keeps its fixed text. Empty when the code has no schedule text.
export function startRefusalMessage({ code, details, hospitalName, visitDate }) {
  if (code !== "visit_date_out_of_schedule_window") return visitErrorMessage(code);
  const endDate = details?.schedule_end_date;
  if (!endDate) {
    return `${hospitalName} 還沒有公布這一天的門診表，公布後系統會自動核對你存的草稿。`;
  }
  return notYetPublishedNotice({
    hospitalName,
    endDate,
    visitDate,
    releaseTime: details?.release_time,
  });
}
