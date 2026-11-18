// Pure decisions behind the setup form: pre-submit validation, the manual
// clinic-code parse preview and the unsaved-change check. main.ts reads the
// form and renders; the rules live here so node --test can cover them. The
// frontend knows no hospital: labels, capability and the clinic schedule all
// arrive from the served catalog and the backend.

import { rosterClinicError } from "./schedule-window.js";

function escapeHtml(value) {
  return value.replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char] || char);
}

// Field errors for a setup form about to be saved. A visit date before today in
// Taipei is an error; today is allowed. A chosen clinic is checked against the
// clinic schedule only when one was returned for this same hospital, department
// and date; with none (manual entry) no clinic check applies and the backend
// Start stays the authoritative check.
export function setupFormErrors({
  date,
  clinic,
  today,
  fullSchedule,
  roster,
  rosterKey,
  selectionKey,
}) {
  const errors = {};
  if (date && date < today) {
    errors.date = "看診日期已過，請選擇今天或之後的日期。";
  }
  const rosterReady = roster !== null && roster !== undefined
    && rosterKey === selectionKey
    && roster.available;
  if (fullSchedule && rosterReady) {
    const clinicError = rosterClinicError(roster, clinic, date === today);
    if (clinicError) errors.clinic_code = clinicError;
  }
  return errors;
}

// The manual clinic-code parse preview, labelled from the catalog. `cls` is the
// preview's extra class and `html` its escaped content; empty html means hidden.
export function clinicCodePreview(labels, value) {
  if (!labels.length || !value) return { cls: "", html: "" };
  const parts = value.split("/").map((part) => part.trim());
  if (parts.length === labels.length && parts.every(Boolean)) {
    const read = labels.map((label, index) => `${escapeHtml(label)} <b>${escapeHtml(parts[index])}</b>`).join("｜");
    return { cls: "", html: `系統讀到：${read} <span class="ok">✓</span>` };
  }
  return { cls: "warn", html: `格式通常為「${escapeHtml(labels.join("/"))}」，請對照院方進度頁。` };
}

// The single-value form fields hasUnsavedChanges compares, by input name.
export const SETUP_FIELDS = ["hospital", "date", "patient_number", "department_code", "clinic_code", "session"];

// Whether the form differs from what was saved. `current` holds only the fields
// present in the form (hidden cascade fields are absent); `recipient_ids` is
// absent when the recipient list is not shown. Automatically selected defaults
// are not edits: the only hospital, its first department, and an empty derived
// session. Recipient order does not matter.
export function hasUnsavedChanges({
  current,
  saved,
  firstHospital,
  firstDepartmentOf,
  initialPatientNumber,
}) {
  const has = (name) => current[name] !== undefined;
  const changed = (name, savedValue) => has(name) && current[name] !== savedValue;
  const baselineRecipients = saved?.recipients.map((recipient) => recipient.id).sort() ?? [];
  const currentRecipients = has("recipient_ids")
    ? [...current.recipient_ids].sort()
    : baselineRecipients;
  const currentHospital = current.hospital ?? firstHospital;
  const defaultDept = firstDepartmentOf(currentHospital) ?? "";
  const session = current.session ?? "";
  return changed("hospital", saved?.hospital ?? firstHospital)
    || changed("date", saved?.date ?? "")
    || (has("patient_number") && current.patient_number !== (initialPatientNumber ?? ""))
    || changed("department_code", saved?.department_code ?? defaultDept)
    || changed("clinic_code", saved?.clinic_code ?? "")
    || (has("session") && session !== "" && session !== (saved?.session ?? "morning"))
    || currentRecipients.join("\u0000") !== baselineRecipients.join("\u0000");
}
