// Pre-submit checks for the setup form that must run before a draft enters
// monitoring. Authoritative checks still run in the backend Start; this only
// improves the setup experience. No clinic schedule date rule lives here: when
// the backend returned a clinic schedule for the chosen day, the chosen clinic
// must be in it, whatever the day.

// `roster` is the backend's answer for exactly the chosen hospital, department
// and date, or null when none was returned (or it was not available).
export function validateSetup({ date, today, clinic, roster }) {
  const errors = {};
  if (date && date < today) {
    errors.date = "看診日期已過，請選擇今天或之後的日期。";
  }
  if (roster && roster.available) {
    if (!clinic) {
      errors.clinic_code = "請選擇醫師。";
    } else if (!roster.clinics.some((option) => option.clinic_code === clinic)) {
      errors.clinic_code = date === today
        ? "所選醫師當天該科沒有看診，請重新選擇。"
        : "所選醫師該日該科沒有排班，請重新選擇。";
    }
  }
  return errors;
}
