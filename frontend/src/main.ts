import "./style.css";
import {
  OrganizerApiError,
  correctVisit,
  createInvitation,
  createVisit,
  getVisitCorrection,
  listClinics,
  listHospitals,
  listRecipients,
  listVisits,
  removeVisitRecipient,
  startVisit,
  stopVisit,
  updateVisit,
  withdrawMember,
} from "./organizer-api.js";
import type {
  ClinicRoster,
  Hospital,
  HospitalCatalogEntry,
  OrganizerVisit,
  Recipient,
  VisitInput,
} from "./organizer-api.js";
import { canRequestStart, formatSourceStatus, formatVisitState, sendInterruptionNotice, visitStatusKey } from "./visit-state.js";
import { sourceLinkMarkup } from "./source-link.js";
import { clinicCodePreview, hasUnsavedChanges, SETUP_FIELDS, setupFormErrors } from "./setup-form.js";
import { projectDashboardVisits } from "./dashboard-projection.js";
import {
  currentNumberOnlyNotice,
  degradeNotice as scheduleDegradeNotice,
  unpublishedDayNotice,
} from "./schedule-window.js";
import { startRefusalMessage as scheduleStartRefusalMessage, visitErrorMessage } from "./refusal-texts.js";

const app = document.querySelector<HTMLElement>("#app");
const serviceStatus = document.querySelector<HTMLSpanElement>("#service-status");
const sessionNames: Record<OrganizerVisit["session"], string> = {
  morning: "早診",
  afternoon: "午診",
  evening: "晚診",
};
const sourceReasons: Record<string, string> = {
  none: "來源資料已核對",
  no_observation: "尚無院方觀察",
  timeout: "院方來源逾時",
  stale_sample: "來源資料已過期",
  untrusted_source: "來源可信度尚未確認",
  scope_mismatch: "來源診次與提醒不相符",
  empty_result: "來源沒有可用資料",
  schema_drift: "來源格式無法辨識",
  access_denied: "來源拒絕讀取",
  ambiguous_match: "來源資料無法唯一核對",
  invalid_data: "來源資料無效",
};

let recipients: Recipient[] = [];
let visits: OrganizerVisit[] = [];
let sendingInterrupted = false;
let hospitals: HospitalCatalogEntry[] = [];
let roster: ClinicRoster | null = null;
let rosterLoading = false;
let rosterKey = "";
let formErrors: Record<string, string> = {};
let authorized = false;
let localTestMode = false;
let loading = false;
let message = "";
let refreshWarning = "";
let formSaving = false;
let editing: { visit: OrganizerVisit; mode: "update" | "correct" } | null = null;
let formValues: Record<string, string | string[]> | null = null;
let initialPatientNumber: string | null = null;
let discardFormOnNextRender = false;
const pendingStops = new Set<string>();
const pendingStarts = new Set<string>();
const startFailures = new Map<string, string>();
const pendingRecipientRemovals = new Set<string>();
let stoppingRefreshTimer: number | null = null;
let draftsCollapsed = true;
let invitationUrl: string | null = null;
let invitationCreating = false;
let invitationError = "";
let copyFeedback = "";
const pendingMemberWithdrawals = new Set<string>();

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char] || char);
}

function text(value: string | number | null | undefined): string {
  return value === null || value === undefined || value === "" ? "尚無資料" : String(value);
}

function recipientLabel(recipient: Recipient): string {
  const label = recipient.display_name.trim();
  return label || `成員 · ${recipient.id.slice(0, 6)}`;
}

function hospitalEntry(hospital: string): HospitalCatalogEntry | undefined {
  return hospitals.find((entry) => entry.hospital === hospital);
}

function hospitalDisplayName(hospital: string): string {
  return hospitalEntry(hospital)?.display_name ?? hospital;
}

function firstHospital(): string {
  return hospitals[0]?.hospital ?? "";
}

function todayTaipei(): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Taipei",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

function selectionKey(hospital: string, department: string, date: string): string {
  return `${hospital}\u0000${department}\u0000${date}`;
}

function degradeNotice(reason: string): string {
  return scheduleDegradeNotice(reason);
}

function formatCheckedAt(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "尚無資料";
  const checkedAt = new Date(value);
  if (Number.isNaN(checkedAt.getTime())) return "時間格式無效";
  return new Intl.DateTimeFormat("zh-TW", {
    timeZone: "Asia/Taipei",
    calendar: "gregory",
    numberingSystem: "latn",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(checkedAt);
}

function errorText(error: unknown): string {
  if (!(error instanceof OrganizerApiError)) return "連線失敗，請確認服務後重試。";
  // Start refusal texts live in the one map in refusal-texts.js; these two codes
  // come from the setup endpoints, not from Start.
  const labels: Record<string, string> = {
    invalid_request: "資料不完整或格式不正確，請檢查後再試。",
    hospital_unsupported: "這家醫院目前無法設定提醒，請改選其他醫院。",
  };
  if (error.status === 401 || error.status === 403) return "登入已失效或目前帳號沒有管理權限。";
  const refusalText = visitErrorMessage(error.code, { visitDate: error.visitDate });
  if (refusalText) return refusalText;
  return labels[error.code] || "操作未完成，請重新載入後再試。";
}

function startFailureText(error: unknown, item: OrganizerVisit): string {
  if (error instanceof OrganizerApiError) {
    const refusal = scheduleStartRefusalMessage({
      code: error.code,
      hospitalName: hospitalEntry(item.hospital)?.display_name,
      scheduleEnd: error.scheduleEnd,
      releaseTime: error.releaseTime,
      // The backend names the day Start opens when it refuses a start-day-only
      // hospital; otherwise the draft's own visit date is the day in question.
      visitDate: error.visitDate ?? item.date,
    });
    if (refusal) return refusal;
  }
  return errorText(error);
}

function renderLogin(): string {
  return `<section class="panel login-panel" aria-labelledby="login-heading">
    <p class="eyebrow">管理者登入</p><h1 id="login-heading">登入以管理家人提醒</h1>
    <p class="intro">只有已授權的管理者能查看或修改提醒。請使用已設定的 LINE Login。</p>
    ${message ? `<p class="message message-warning" role="status">${escapeHtml(message)}</p>` : ""}
    <div class="login-actions"><a class="primary-button link-button" href="/auth/line">使用 LINE Login</a>${localTestMode ? '<button class="secondary-button" id="synthetic-login" type="button">本機合成測試登入</button>' : ""}</div>
    ${localTestMode ? '<p class="gate-note">本機合成測試登入不會呼叫 LINE。</p>' : ""}
  </section>`;
}

function recipientChoices(selected: string[], allowedRecipientIds?: Set<string>): string {
  const choices = allowedRecipientIds
    ? recipients.filter((recipient) => allowedRecipientIds.has(recipient.id))
    : recipients;
  if (!choices.length) return `<p class="empty-inline">目前沒有已同意且可用的通知對象。</p>`;
  return choices.map((recipient) => `<label class="recipient-choice"><input type="checkbox" name="recipient_ids" value="${escapeHtml(recipient.id)}" ${selected.includes(recipient.id) ? "checked" : ""}><span>${escapeHtml(recipientLabel(recipient))}</span></label>`).join("");
}

function rememberFormValues(): void {
  const form = document.querySelector<HTMLFormElement>("#visit-form");
  if (!form) return;
  const data = new FormData(form);
  const prev = formValues ?? {};
  const item = editing?.visit;
  // A cascading form hides fields that the current mode does not use; keep the
  // previous value for any field absent from the DOM instead of clearing it.
  const keep = (name: string, fallback: string): string => {
    if (form.elements.namedItem(name)) return String(data.get(name) ?? "");
    const stored = prev[name];
    return typeof stored === "string" ? stored : fallback;
  };
  formValues = {
    hospital: keep("hospital", item?.hospital ?? firstHospital()),
    date: keep("date", item?.date ?? ""),
    patient_number: keep("patient_number", initialPatientNumber ?? ""),
    department_code: keep("department_code", item?.department_code ?? ""),
    clinic_code: keep("clinic_code", item?.clinic_code ?? ""),
    session: keep("session", item?.session ?? "morning"),
    recipient_ids: form.elements.namedItem("recipient_ids")
      ? data.getAll("recipient_ids").map(String)
      : Array.isArray(prev.recipient_ids)
        ? prev.recipient_ids
        : [],
  };
}

function formValue(name: string, fallback: string): string {
  const value = formValues?.[name];
  return typeof value === "string" ? value : fallback;
}

function hasUnsavedFormChanges(): boolean {
  const form = document.querySelector<HTMLFormElement>("#visit-form");
  if (!form) return false;
  const data = new FormData(form);
  const current: Record<string, string | string[]> = {};
  for (const name of SETUP_FIELDS) {
    if (form.elements.namedItem(name)) current[name] = String(data.get(name) ?? "");
  }
  if (form.elements.namedItem("recipient_ids")) current.recipient_ids = data.getAll("recipient_ids").map(String);
  return hasUnsavedChanges({
    current,
    saved: editing?.visit,
    firstHospital: firstHospital(),
    firstDepartmentOf: (hospital) => hospitalEntry(hospital)?.departments[0]?.code,
    initialPatientNumber,
  });
}

function blockNavigationWithUnsavedChanges(): boolean {
  if (!hasUnsavedFormChanges()) return false;
  message = "目前設定尚未儲存。請先儲存或取消修正，再開啟其他提醒。";
  renderDashboard();
  return true;
}

function errorMarkup(field: string): string {
  return formErrors[field]
    ? `<p class="inline-error" role="alert">${escapeHtml(formErrors[field])}</p>`
    : "";
}

// The manual clinic-code parse preview, labelled from the catalog so it carries
// no hard-coded hospital format. Returned separately so it can be patched in
// place on input without re-rendering (and destroying) the whole form.
function clinicPreviewMarkup(labels: readonly string[], value: string): string {
  const { cls, html } = clinicCodePreview(labels, value);
  return `<div class="parse-preview ${cls}" id="clinic-preview"${html ? "" : " hidden"}>${html}</div>`;
}

function clinicSectionMarkup(
  entry: HospitalCatalogEntry,
  selectedDept: string,
  selectedDate: string,
  selectedClinic: string,
  selectedSession: string,
): string {
  const selectionReady = Boolean(selectedDept) && Boolean(selectedDate);
  if (!selectionReady) {
    return `<p class="gate-note">請先選擇科別與看診日期。</p>`;
  }
  const key = selectionKey(entry.hospital, selectedDept, selectedDate);
  const rosterReady = roster !== null && rosterKey === key;
  const today = todayTaipei();
  // A full-schedule hospital is asked for the day's clinics whenever
  // department and date are set and the date is not past; the answer decides
  // between the picker and the not-yet-published notice.
  const useRoster = entry.capability === "full_schedule" && selectedDate >= today;

  if (useRoster && !rosterReady) {
    const loadingText = selectedDate === today
      ? "正在向院方讀取當天門診名單…"
      : "正在向院方讀取該日門診排班…";
    return `<div class="loading-row"><span class="spinner" aria-hidden="true"></span><span role="status">${loadingText}</span></div>`;
  }
  if (useRoster && rosterReady && roster?.available) {
    const options = roster.clinics
      .map((clinic) => `<option value="${escapeHtml(clinic.clinic_code)}" ${selectedClinic === clinic.clinic_code ? "selected" : ""}>${escapeHtml(clinic.label)}</option>`)
      .join("");
    const chosen = roster.clinics.find((clinic) => clinic.clinic_code === selectedClinic);
    const helper = selectedDate === today
      ? "只列出當天該科實際看診的醫師；診間與診次自動帶入。來源吻合不代表號碼已與現場燈號核實。"
      : "只列出該日該科排班的醫師；診間與診次自動帶入。院方可能調整排班，系統每天會重新核對，按開始時也會再核對一次。";
    const detailRows = (chosen?.details ?? [])
      .map((detail) => `<div><dt>${escapeHtml(detail.label)}</dt><dd>${escapeHtml(detail.value)}</dd></div>`)
      .join("");
    const detailList = detailRows ? `<dl class="clinic-details" aria-label="院方公布的這個診的資料">${detailRows}</dl>` : "";
    return `<label class="field"><span>醫師 / 診間</span><select name="clinic_code" required><option value="" ${selectedClinic ? "" : "selected"}>請選擇醫師</option>${options}</select><input type="hidden" name="session" value="${escapeHtml(chosen?.session ?? "")}">${detailList}<small>${helper}</small>${errorMarkup("clinic_code")}</label>`;
  }

  // Manual entry: a day the hospital has not published, past date (defensive),
  // a held or unavailable roster, or a current-number-only source. Reuse the
  // per-hospital source link and show a live parse preview so the user can
  // confirm the three parts.
  const reason = rosterReady && roster
    ? roster.reason
    : selectedDate < today
      ? "visit_date_past"
      : "no_observation";
  const notice = rosterReady && roster?.reason === "visit_date_out_of_schedule_window" && roster.schedule_end
    ? unpublishedDayNotice({
      hospitalName: entry.display_name,
      scheduleEnd: roster.schedule_end,
      releaseTime: roster.release_time,
      visitDate: selectedDate,
    })
    : entry.capability === "current_number_only"
      ? currentNumberOnlyNotice()
      : degradeNotice(reason);
  // The part labels come from the catalog, so the preview carries no hard-coded
  // hospital format. A mismatch is only a hint, never a submit gate.
  const labels = entry.clinic_code_labels;
  const preview = clinicPreviewMarkup(labels, selectedClinic);
  const formatHint = labels.length
    ? `照院方進度頁上顯示的「${escapeHtml(labels.join(" / "))}」文字填寫。`
    : "照院方進度頁上顯示的資訊填寫。";
  const sessionOptions = (["morning", "afternoon", "evening"] as const)
    .map((value) => `<option value="${value}" ${selectedSession === value ? "selected" : ""}>${sessionNames[value]}</option>`)
    .join("");
  return `<p class="edit-notice">${escapeHtml(notice)}</p>
    <p class="source-ref">${sourceLinkMarkup(entry.source_url)}<small>${formatHint}</small></p>
    <label class="field"><span>診間代碼</span><input name="clinic_code" maxlength="64" value="${escapeHtml(selectedClinic)}" autocomplete="off" required>${preview}<small>比對忽略大小寫、空白、標點；上面的即時預覽顯示系統讀到的內容供你核對。</small>${errorMarkup("clinic_code")}</label>
    <label class="field"><span>診次</span><select name="session" required>${sessionOptions}</select>${errorMarkup("session")}</label>`;
}

function formMarkup(): string {
  const item = editing?.visit;
  const storedRecipients = item?.recipients.map((recipient) => recipient.id) ?? [];
  const allowedRecipientIds = editing?.mode === "correct" ? new Set(storedRecipients) : undefined;
  const draftRecipients = formValues?.recipient_ids;
  const selectedRecipients = Array.isArray(draftRecipients) ? draftRecipients : storedRecipients;

  const selectedHospital = formValue("hospital", item?.hospital ?? firstHospital());
  const entry = hospitalEntry(selectedHospital);
  const capability = entry?.capability ?? "unsupported";
  const departments = entry?.departments ?? [];
  const selectedDept = formValue("department_code", item?.department_code ?? departments[0]?.code ?? "");
  const selectedDate = formValue("date", item?.date ?? "");
  const selectedClinic = formValue("clinic_code", item?.clinic_code ?? "");
  const selectedSession = formValue("session", item?.session ?? "morning");

  const correctionIsExpired = item?.state === "expired";
  const formTitle = editing?.mode === "correct"
    ? correctionIsExpired ? "修正已結束的提醒" : "修正已停止的提醒"
    : item ? "修正草稿" : "建立候診提醒";
  const submitLabel = formSaving ? "儲存中…" : editing?.mode === "correct" ? "儲存修正並回到草稿" : item ? "儲存草稿" : "建立草稿";
  const showCancel = Boolean(item) || (!item && formValues !== null && hasUnsavedFormChanges());
  const cancelLabel = item ? "取消修正" : "清除未儲存草稿";

  const hospitalRadios = hospitals.length
    ? hospitals.map((hospital) => {
      const disabled = hospital.capability === "unsupported";
      return `<label class="choice"><input type="radio" name="hospital" value="${escapeHtml(hospital.hospital)}" ${selectedHospital === hospital.hospital ? "checked" : ""} ${disabled ? "disabled" : ""} required><span>${escapeHtml(hospital.display_name)}</span>${disabled ? `<span class="choice-note">尚未支援</span>` : ""}</label>`;
    }).join("")
    : `<p class="empty-inline">正在載入醫院清單…</p>`;

  let body: string;
  if (!entry || capability === "unsupported") {
    body = `<div class="state-off" role="status"><p class="state-off-title">此醫院尚未支援自動候診監控</p><p>目前無法取得這家醫院的即時候診進度，待來源確認後開通。</p></div>`;
  } else {
    const deptOptions = departments
      .map((dept) => `<option value="${escapeHtml(dept.code)}" ${selectedDept === dept.code ? "selected" : ""}>${escapeHtml(dept.display_name)}</option>`)
      .join("");
    const deptPrompt = departments.length > 1 ? `<option value="" ${selectedDept ? "" : "selected"}>請選擇科別</option>` : "";
    const departmentField = `<label class="field"><span>科別</span><select name="department_code" required>${deptPrompt}${deptOptions}</select>${errorMarkup("department_code")}</label>`;
    const dateField = `<label class="field"><span>看診日期</span><input name="date" type="date" value="${escapeHtml(selectedDate)}" required>${errorMarkup("date")}</label>`;
    const clinicSection = clinicSectionMarkup(entry, selectedDept, selectedDate, selectedClinic, selectedSession);
    const patientField = `<label class="field"><span>掛號序號</span><input name="patient_number" type="number" min="1" max="999999" value="${escapeHtml(formValue("patient_number", initialPatientNumber ?? ""))}" required inputmode="numeric"><small>僅供這筆提醒使用；已儲存草稿會顯示序號，方便辨識。</small>${errorMarkup("patient_number")}</label>`;
    body = `<div class="form-grid">${departmentField}${dateField}</div>${clinicSection}${patientField}`;
  }

  const rosterPending = Boolean(entry) && capability === "full_schedule" && Boolean(selectedDept) && Boolean(selectedDate)
    && selectedDate >= todayTaipei()
    && !(roster !== null && rosterKey === selectionKey(selectedHospital, selectedDept, selectedDate));
  const submitDisabled = formSaving || rosterPending || !entry || capability === "unsupported" || hospitals.length === 0;

  return `<section class="panel" aria-labelledby="setup-heading">
    <div class="panel-heading"><div><p class="eyebrow">提醒設定</p><h2 id="setup-heading">${formTitle}</h2></div><span class="step-count">${item ? formatVisitState(item.state) : "新草稿"}</span></div>
    ${item ? `<p class="edit-notice" role="status">你正在修改已儲存的${editing?.mode === "correct" ? correctionIsExpired ? "已結束提醒" : "已停止提醒" : "草稿"}。畫面上的變更尚未儲存；取消會捨棄這次編輯，儲存後仍須重新檢查才能開始提醒。</p>` : `<p class="intro">先建立草稿，再由提醒清單檢查並開始。建立或儲存草稿不會啟動監控，也不會傳送通知。</p>`}
    <form id="visit-form" novalidate>
      <fieldset class="hospital-options"><legend>醫院</legend>${hospitalRadios}</fieldset>
      ${body}
      <fieldset class="recipient-panel"><legend>通知對象</legend><div class="recipient-list">${recipientChoices(selectedRecipients, allowedRecipientIds)}</div>${allowedRecipientIds ? `<p class="recipient-note">第一次成功啟動後，不能新增通知對象；修正時只能保留或移除原有對象。</p>` : ""}</fieldset>
      <div class="action-row"><button class="primary-button" type="submit" ${submitDisabled ? "disabled" : ""}>${submitLabel}</button>${showCancel ? `<button class="secondary-button" id="cancel-edit" type="button" ${formSaving ? "disabled" : ""}>${cancelLabel}</button>` : ""}</div>
      ${formSaving ? `<p class="inline-state" role="status">正在儲存${editing?.mode === "correct" ? "修正" : "草稿"}…</p>` : ""}
    </form>
    <p class="gate-note">儲存只會建立或更新草稿。提醒清單會顯示 API 提供的院方官方來源連結；連結不代表已查詢院方資料。</p>
  </section>`;
}

function visitCard(item: OrganizerVisit): string {
  const stateKey = visitStatusKey(item);
  const active = item.state === "active";
  const pendingStop = pendingStops.has(item.id);
  const displayStateKey = pendingStop ? "stopping" : stateKey;
  const pendingStart = pendingStarts.has(item.id);
  const interruptionNotice = sendInterruptionNotice(item, sendingInterrupted);
  const canRemoveRecipients = ["active", "stopped", "expired"].includes(item.state);
  const cannotRemoveLastRecipient = canRemoveRecipients && item.recipients.length === 1;
  const recipientsSummary = item.recipients.length
    ? `<div><ul class="recipient-summary">${item.recipients.map((recipient) => {
      const removalKey = `${item.id}\u0000${recipient.id}`;
      const pendingRemoval = pendingRecipientRemovals.has(removalKey);
      const label = recipientLabel(recipient);
      return `<li><span>${escapeHtml(label)}</span>${canRemoveRecipients ? `<button class="recipient-remove-button" type="button" data-remove-visit="${escapeHtml(item.id)}" data-remove-recipient="${escapeHtml(recipient.id)}" aria-label="移除通知對象 ${escapeHtml(label)}" ${pendingStop || pendingRemoval || cannotRemoveLastRecipient ? "disabled" : ""}>${pendingRemoval ? "移除中…" : "移除"}</button>` : ""}</li>`;
    }).join("")}</ul>${cannotRemoveLastRecipient ? `<p class="gate-note">至少保留一位通知對象，才能繼續提醒或日後重新啟動。</p>` : ""}</div>`
    : "沒有選取通知對象";
  const notification = item.notification;
  const sourceStatus = item.source_read?.status ?? "unavailable";
  const sourceReason = sourceReasons[item.source_read?.reason] ?? "來源狀態尚未提供";
  const patientNumberRow = typeof item.patient_number === "number"
    ? `<div><dt>掛號序號</dt><dd>${escapeHtml(String(item.patient_number))}</dd></div>`
    : "";
  return `<article class="visit-card" aria-labelledby="visit-${escapeHtml(item.id)}">
    <div class="visit-heading"><div><p class="eyebrow">${escapeHtml(hospitalDisplayName(item.hospital))}</p><h3 id="visit-${escapeHtml(item.id)}">${escapeHtml(item.date)} · ${escapeHtml(item.department_code)} · ${escapeHtml(item.clinic_code)}</h3><p class="visit-session">${escapeHtml(sessionNames[item.session])}（${escapeHtml(item.session)}）</p></div><span class="state state-${displayStateKey}">${pendingStop ? "停止中" : stateKey === "source-unavailable" ? "來源暫不可用 · 草稿" : stateKey === "terminal" ? "已結束" : formatVisitState(item.state)}</span></div>
    <dl class="details">
      <div><dt>科別・診間・診次</dt><dd>${escapeHtml(item.department_code)}・${escapeHtml(item.clinic_code)}・${escapeHtml(item.session)}</dd></div>
      ${patientNumberRow}
      <div><dt>院方資料來源</dt><dd>${sourceLinkMarkup(item.source_url)}</dd></div>
      <div><dt>通知對象</dt><dd>${recipientsSummary}</dd></div>
      <div><dt>最近檢查</dt><dd>${escapeHtml(formatCheckedAt(item.observation?.checked_at))}</dd></div>
      <div><dt>院方觀察</dt><dd>${item.observation?.current_number ? `目前號碼 ${escapeHtml(String(item.observation.current_number))}` : "尚無可用的號碼觀察"}</dd></div>
      <div><dt>來源狀態</dt><dd>${escapeHtml(formatSourceStatus(sourceStatus))} · ${escapeHtml(sourceReason)}</dd></div>
      <div><dt>訊息傳送結果</dt><dd>共 ${notification.count} 則；已接受 ${notification.accepted} 則；需留意 ${notification.issues} 則</dd></div>
    </dl>
    ${active ? `<div class="stop-row"><div><p>${pendingStop ? "停止請求處理中…" : "監控中。停止確認後，系統會停止後續檢查與通知。"}</p><small>停止完成前，狀態仍以服務回覆為準。</small></div><button class="stop-button" type="button" data-stop="${escapeHtml(item.id)}" ${pendingStop ? "disabled" : ""}>${pendingStop ? "停止中" : "停止提醒"}</button></div>` : ""}
    ${interruptionNotice ? `<p class="inline-state send-interruption" role="status">${escapeHtml(interruptionNotice)}</p>` : ""}
    ${item.state === "stopping" ? `<p class="inline-state" role="status">停止已送出，正在等候關閉確認。</p>` : ""}
    ${item.state === "stopped" ? `<p class="inline-state" role="status">提醒已停止。</p>` : ""}
    ${item.state === "expired" ? `<p class="inline-state" role="status">此提醒已結束。修正日期或診次並儲存後，可重新檢查並啟動同一筆提醒。</p>` : ""}
    ${pendingStart ? `<p class="inline-state" role="status">正在檢查可信院方觀察…</p>` : ""}
    ${startFailures.has(item.id) && !pendingStart && item.state === "draft" ? `<p class="inline-state inline-error" role="alert">${escapeHtml(startFailures.get(item.id) ?? "")}</p>` : ""}
    <div class="visit-actions">
      ${item.state === "draft" ? `<button class="secondary-button" type="button" data-edit="${escapeHtml(item.id)}">修正草稿</button><button class="primary-button" type="button" data-start="${escapeHtml(item.id)}" ${canRequestStart(item) && !pendingStart && editing?.visit.id !== item.id ? "" : "disabled"}>${pendingStart ? "重新檢查中…" : "重新檢查並開始提醒"}</button>` : ""}
      ${item.state === "stopped" ? `<button class="secondary-button" type="button" data-correct="${escapeHtml(item.id)}">修正後重新檢查</button>` : ""}
      ${item.state === "expired" ? `<button class="secondary-button" type="button" data-correct="${escapeHtml(item.id)}">修正後重新啟動</button>` : ""}
    </div>
    ${item.state === "draft" && editing?.visit.id === item.id ? `<p class="gate-note">清單仍顯示已儲存的草稿。先儲存或取消修正，再重新檢查並開始。</p>` : item.state === "draft" && !canRequestStart(item) ? `<p class="gate-note">開始前請填妥醫院、日期、科別、診間、診次，並選擇至少一位通知對象。</p>` : item.state === "draft" ? `<p class="gate-note">服務會重新檢查來源資料。只有取得新鮮、可信且完全符合診次的觀察後，服務才會回覆啟動成功；失敗時維持草稿。</p>` : ""}
  </article>`;
}

function membersPanel(): string {
  return `<section class="panel members-panel" aria-labelledby="members-heading">
    <div class="panel-heading"><div><p class="eyebrow">成員管理</p><h2 id="members-heading">家庭成員</h2></div><div class="invite-controls"><label class="invite-label" for="member-label">成員稱呼</label><input id="member-label" type="text" maxlength="40" placeholder="例如：媽媽"><button class="primary-button" id="invite-member" type="button" ${invitationCreating ? "disabled" : ""}>${invitationCreating ? "建立邀請中…" : "邀請新成員"}</button></div></div>
    ${invitationError ? `<p class="message message-warning" role="alert">${escapeHtml(invitationError)}</p>` : ""}
    ${invitationUrl ? `<div class="invitation-link"><label for="invitation-url-input">邀請連結（限一次使用）</label><div class="invitation-link-row"><input id="invitation-url-input" type="text" readonly value="${escapeHtml(invitationUrl)}"><button class="secondary-button" id="copy-invitation" type="button">${copyFeedback || "複製連結"}</button></div><p class="gate-note">請自行透過你的 LINE 將這個連結傳送給家人；連結限一次使用，使用後即失效。</p></div>` : ""}
    ${recipients.length
      ? `<ul class="member-list">${recipients.map((recipient) => {
        const pending = pendingMemberWithdrawals.has(recipient.id);
        const label = recipientLabel(recipient);
        return `<li><span>${escapeHtml(label)}</span><button class="recipient-remove-button" type="button" data-withdraw-member="${escapeHtml(recipient.id)}" aria-label="移除成員 ${escapeHtml(label)}" ${pending ? "disabled" : ""}>${pending ? "移除中…" : "移除"}</button></li>`;
      }).join("")}</ul>`
      : `<p class="empty-inline">目前沒有已加入的成員。</p>`}
  </section>`;
}

function renderDashboard(preserveCurrentForm = true): void {
  if (!app) return;
  if (preserveCurrentForm && !discardFormOnNextRender) rememberFormValues();
  discardFormOnNextRender = false;
  if (!authorized) {
    app.innerHTML = renderLogin();
    document.querySelector<HTMLButtonElement>("#synthetic-login")?.addEventListener("click", voidSyntheticLogin);
    return;
  }
  const { drafts, reminders, reminderCount } = projectDashboardVisits(visits);
  app.innerHTML = `<div class="dashboard-top"><div><p class="eyebrow">安全的提醒管理</p><h1>看診提醒</h1></div><button class="secondary-button refresh-button" id="refresh" type="button" ${loading ? "disabled" : ""}>重新整理</button></div>
    ${message ? `<p class="message" role="status">${escapeHtml(message)}</p>` : ""}
    ${refreshWarning ? `<p class="message message-warning" role="status">${escapeHtml(refreshWarning)}</p>` : ""}
    ${membersPanel()}
    ${formMarkup()}
    <section class="visits saved-drafts" aria-labelledby="drafts-heading"><div class="section-heading"><div><p class="eyebrow">提醒設定</p><h2 id="drafts-heading">已儲存草稿 <span class="draft-count">${drafts.length}</span></h2></div><button class="secondary-button drafts-toggle" type="button" data-drafts-toggle aria-expanded="${!draftsCollapsed}" aria-controls="saved-drafts-list">${draftsCollapsed ? "展開草稿" : "收合草稿"}</button></div><div id="saved-drafts-list" class="draft-list" ${draftsCollapsed ? "hidden" : ""}>${drafts.length ? drafts.map(visitCard).join("") : `<div class="empty-state"><h3>尚無已儲存草稿</h3><p>建立草稿後，會顯示在這裡。</p></div>`}</div></section>
    <section class="visits" aria-labelledby="visits-heading"><div class="section-heading"><div><p class="eyebrow">狀態與控制</p><h2 id="visits-heading">提醒清單 <span class="draft-count">${reminderCount}</span></h2></div></div>${reminders.length ? reminders.map(visitCard).join("") : `<div class="empty-state"><h3>尚無提醒狀態</h3><p>執行中、已停止或已結束的提醒會顯示在這裡。</p></div>`}</section>`;
  bindActions();
}

function scheduleStoppingRefresh(): void {
  if (stoppingRefreshTimer !== null) {
    window.clearTimeout(stoppingRefreshTimer);
    stoppingRefreshTimer = null;
  }
  if (!authorized || !visits.some((visit) => visit.state === "stopping")) return;
  stoppingRefreshTimer = window.setTimeout(() => {
    stoppingRefreshTimer = null;
    void loadDashboard();
  }, 1000);
}

async function maybeFetchRoster(): Promise<void> {
  if (!authorized || rosterLoading) return;
  const item = editing?.visit;
  const hospital = formValue("hospital", item?.hospital ?? firstHospital());
  const entry = hospitalEntry(hospital);
  if (!entry || entry.capability !== "full_schedule") return;
  const department = formValue("department_code", item?.department_code ?? entry.departments[0]?.code ?? "");
  const date = formValue("date", item?.date ?? "");
  // Ask for the day's clinics whenever department and date are set and the
  // date is not past; the backend says which days the hospital has published.
  if (!department || !date || date < todayTaipei()) return;
  const key = selectionKey(hospital, department, date);
  if (roster !== null && rosterKey === key) return;
  rosterLoading = true;
  try {
    roster = await listClinics(hospital, department, date);
  } catch {
    roster = { available: false, reason: "no_observation", clinics: [] };
  }
  rosterKey = key;
  rosterLoading = false;
  renderDashboard(false);
}

async function loadDashboard(preserveSaveConfirmation = false): Promise<void> {
  if (!serviceStatus) return;
  loading = true;
  try {
    const health = await fetch("/api/healthz", { headers: { accept: "application/json" } });
    if (!health.ok) throw new Error("service unavailable");
    localTestMode = (await health.json()).mode === "local-test";
    serviceStatus.textContent = "服務正常";
    serviceStatus.className = "status status-ok";
    const [recipientRoster, projection, catalog] = await Promise.all([
      listRecipients(),
      listVisits(),
      listHospitals(),
    ]);
    recipients = recipientRoster.recipients;
    visits = projection.visits;
    sendingInterrupted = projection.sending_interrupted === true;
    hospitals = catalog.hospitals;
    authorized = true;
    refreshWarning = "";
  } catch (error) {
    if (error instanceof OrganizerApiError && (error.status === 401 || error.status === 403)) {
      authorized = false;
      message = "請登入已授權的管理者帳號。";
    } else {
      serviceStatus.textContent = "服務不可用";
      serviceStatus.className = "status status-pending";
      if (preserveSaveConfirmation && authorized) {
        refreshWarning = "草稿已儲存，但清單更新失敗。請重新整理確認狀態。";
      } else if (authorized) {
        refreshWarning = visits.some((visit) => visit.state === "stopping")
          ? `提醒狀態更新失敗，將自動重試。${errorText(error)}`
          : errorText(error);
      } else {
        message = errorText(error);
      }
    }
  } finally {
    loading = false;
    renderDashboard();
    scheduleStoppingRefresh();
  }
}

async function voidSyntheticLogin(): Promise<void> {
  const button = document.querySelector<HTMLButtonElement>("#synthetic-login");
  if (button) button.disabled = true;
  try {
    const response = await fetch("/__niy006_test/organizer-session", { method: "POST", headers: { accept: "application/json" } });
    if (!response.ok) throw new Error("local synthetic login is not enabled");
    message = "已建立本機合成管理者工作階段。";
    await loadDashboard();
  } catch {
    message = "本機合成登入未啟用。請只在 wrangler.niy006.test.jsonc 本機測試綁定中使用。";
    renderDashboard();
  }
}

function readForm(form: HTMLFormElement): VisitInput | null {
  const data = new FormData(form);
  const hospital = data.get("hospital");
  const date = data.get("date");
  const department = data.get("department_code");
  const clinic = data.get("clinic_code");
  const session = data.get("session");
  const patientNumber = Number(data.get("patient_number"));
  const selectedRecipients = data.getAll("recipient_ids").filter((item): item is string => typeof item === "string");
  if (typeof hospital !== "string" || !hospital || typeof date !== "string" || !date
    || typeof department !== "string" || !department.trim() || typeof clinic !== "string" || !clinic.trim()
    || (session !== "morning" && session !== "afternoon" && session !== "evening")
    || !Number.isSafeInteger(patientNumber) || patientNumber < 1 || selectedRecipients.length === 0) return null;
  return {
    hospital: hospital as Hospital, date, department_code: department.trim(), clinic_code: clinic.trim(),
    session, patient_number: patientNumber, recipient_ids: selectedRecipients,
  };
}

// Pre-submit validation for the mistake classes that must be caught before a
// draft enters monitoring. Authoritative identity/freshness checks still run in
// the backend Start (fail-closed); this only improves the setup experience.
function validateForm(form: HTMLFormElement): boolean {
  const data = new FormData(form);
  const hospital = String(data.get("hospital") ?? "");
  const department = String(data.get("department_code") ?? "");
  const date = String(data.get("date") ?? "");
  formErrors = setupFormErrors({
    date,
    clinic: String(data.get("clinic_code") ?? "").trim(),
    today: todayTaipei(),
    fullSchedule: hospitalEntry(hospital)?.capability === "full_schedule",
    roster,
    rosterKey,
    selectionKey: selectionKey(hospital, department, date),
  });
  return Object.keys(formErrors).length === 0;
}

function bindActions(): void {
  document.querySelector<HTMLButtonElement>("#invite-member")?.addEventListener("click", async () => {
    if (invitationCreating) return;
    const memberLabel = document.querySelector<HTMLInputElement>("#member-label")?.value.trim() ?? "";
    invitationCreating = true;
    invitationError = "";
    renderDashboard();
    try {
      const result = await createInvitation(memberLabel);
      invitationUrl = result.invitation_url;
    } catch (error) {
      invitationError = errorText(error);
    } finally {
      invitationCreating = false;
      renderDashboard();
    }
  });
  document.querySelector<HTMLButtonElement>("#copy-invitation")?.addEventListener("click", async () => {
    if (!invitationUrl) return;
    try {
      await navigator.clipboard.writeText(invitationUrl);
      copyFeedback = "已複製";
    } catch {
      copyFeedback = "複製失敗，請手動選取連結文字";
    }
    renderDashboard();
    window.setTimeout(() => {
      copyFeedback = "";
      renderDashboard();
    }, 2000);
  });
  document.querySelectorAll<HTMLButtonElement>("[data-withdraw-member]").forEach((button) => button.addEventListener("click", async () => {
    const id = button.dataset.withdrawMember;
    if (!id || pendingMemberWithdrawals.has(id)) return;
    pendingMemberWithdrawals.add(id);
    message = "";
    renderDashboard();
    try {
      await withdrawMember(id);
      message = "已移除成員。";
    } catch (error) {
      message = errorText(error);
    } finally {
      pendingMemberWithdrawals.delete(id);
      await loadDashboard();
    }
  }));
  document.querySelector<HTMLButtonElement>("[data-drafts-toggle]")?.addEventListener("click", () => {
    draftsCollapsed = !draftsCollapsed;
    renderDashboard();
    document.querySelector<HTMLButtonElement>("[data-drafts-toggle]")?.focus();
  });
  document.querySelector<HTMLButtonElement>("#refresh")?.addEventListener("click", () => {
    message = "";
    refreshWarning = "";
    void loadDashboard();
  });
  document.querySelector<HTMLButtonElement>("#cancel-edit")?.addEventListener("click", () => {
    editing = null;
    formValues = null;
    initialPatientNumber = null;
    formErrors = {};
    message = "";
    renderDashboard(false);
  });
  // Reveal-drivers re-render so dependent fields appear and the roster is
  // fetched once hospital + department + date are complete. A clinic *select*
  // also re-renders, to refresh its derived hidden session.
  const rerenderOnChange = (selector: string): void => {
    document.querySelectorAll<HTMLInputElement | HTMLSelectElement>(selector).forEach((element) => {
      element.addEventListener("change", () => {
        rememberFormValues();
        formErrors = {};
        renderDashboard(false);
      });
    });
  };
  rerenderOnChange('#visit-form [name="hospital"]');
  rerenderOnChange('#visit-form select[name="department_code"]');
  rerenderOnChange('#visit-form input[name="date"]');
  rerenderOnChange('#visit-form select[name="clinic_code"]');
  // A free-text clinic code must NOT re-render on every edit: that would drop
  // focus mid-typing and destroy the submit button on blur (losing the click).
  // Patch only the parse preview in place; its value is read from the DOM on
  // submit and captured by rememberFormValues on the next real render.
  const clinicInput = document.querySelector<HTMLInputElement>('#visit-form input[name="clinic_code"]');
  const previewNode = document.querySelector<HTMLElement>("#clinic-preview");
  if (clinicInput && previewNode) {
    clinicInput.addEventListener("input", () => {
      rememberFormValues();
      const hospital = formValue("hospital", editing?.visit.hospital ?? firstHospital());
      const labels = hospitalEntry(hospital)?.clinic_code_labels ?? [];
      const { cls, html } = clinicCodePreview(labels, clinicInput.value);
      previewNode.className = `parse-preview ${cls}`;
      previewNode.innerHTML = html;
      previewNode.hidden = !html;
    });
  }
  document.querySelector<HTMLFormElement>("#visit-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    if (!(form instanceof HTMLFormElement)) return;
    if (!form.reportValidity()) return;
    if (!validateForm(form)) {
      message = "";
      renderDashboard();
      return;
    }
    const input = readForm(form);
    if (!input) {
      message = "請輸入完整診次資料並選擇至少一位通知對象。";
      renderDashboard();
      return;
    }
    formErrors = {};
    if (formSaving) return;
    formSaving = true;
    message = "";
    refreshWarning = "";
    renderDashboard();
    try {
      const previous = editing;
      if (!previous) await createVisit(input);
      else if (previous.mode === "correct") await correctVisit(previous.visit.id, input);
      else await updateVisit(previous.visit.id, input);
      if (previous) startFailures.delete(previous.visit.id);
      editing = null;
      formValues = null;
      initialPatientNumber = null;
      discardFormOnNextRender = true;
      message = previous?.mode === "correct"
        ? "修正已儲存為草稿。請在提醒清單重新檢查並開始。"
        : previous ? "草稿修改已儲存。請在提醒清單重新檢查並開始。"
          : "草稿已建立。建立草稿不會啟動監控或傳送通知。";
      renderDashboard(false);
      await loadDashboard(true);
      formSaving = false;
      renderDashboard(false);
    } catch (error) {
      formSaving = false;
      message = errorText(error);
      renderDashboard();
    }
  });

  document.querySelectorAll<HTMLButtonElement>("[data-edit]").forEach((button) => button.addEventListener("click", async () => {
    const item = visits.find((visit) => visit.id === button.dataset.edit);
    if (!item) return;
    if (blockNavigationWithUnsavedChanges()) return;
    message = "";
    button.disabled = true;
    try {
      const correction = await getVisitCorrection(item.id);
      initialPatientNumber = String(correction.patient_number);
      formValues = null;
      editing = { visit: item, mode: "update" };
      renderDashboard(false);
      document.querySelector("#setup-heading")?.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) {
      message = errorText(error);
      renderDashboard();
    }
  }));
  document.querySelectorAll<HTMLButtonElement>("[data-correct]").forEach((button) => button.addEventListener("click", async () => {
    const item = visits.find((visit) => visit.id === button.dataset.correct);
    if (!item) return;
    if (blockNavigationWithUnsavedChanges()) return;
    message = "";
    button.disabled = true;
    try {
      const correction = await getVisitCorrection(item.id);
      initialPatientNumber = String(correction.patient_number);
      formValues = null;
      editing = { visit: item, mode: "correct" };
      renderDashboard(false);
      document.querySelector("#setup-heading")?.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) {
      message = errorText(error);
      renderDashboard();
    }
  }));
  document.querySelectorAll<HTMLButtonElement>("[data-start]").forEach((button) => button.addEventListener("click", async () => {
    const id = button.dataset.start;
    const item = visits.find((visit) => visit.id === id);
    if (!id || !item || !canRequestStart(item)) return;
    pendingStarts.add(id);
    startFailures.delete(id);
    message = "";
    renderDashboard();
    try {
      const result = await startVisit(id);
      message = result.state === "active" ? "服務已回覆啟動成功。" : "服務尚未確認啟動，請查看清單狀態。";
    } catch (error) {
      startFailures.set(id, startFailureText(error, item));
    } finally {
      pendingStarts.delete(id);
      await loadDashboard();
    }
  }));
  document.querySelectorAll<HTMLButtonElement>("[data-stop]").forEach((button) => button.addEventListener("click", async () => {
    const id = button.dataset.stop;
    if (!id || pendingStops.has(id)) return;
    pendingStops.add(id);
    message = "";
    renderDashboard();
    try {
      const result = await stopVisit(id);
      visits = visits.map((visit) => visit.id === id
        ? { ...visit, state: result.state }
        : visit);
      message = result.state === "stopped" ? "提醒已停止。" : "停止請求已送出，正在等候關閉確認。";
    } catch (error) {
      message = errorText(error);
    } finally {
      pendingStops.delete(id);
      await loadDashboard();
    }
  }));

  document.querySelectorAll<HTMLButtonElement>("[data-remove-visit]").forEach((button) => button.addEventListener("click", async () => {
    const visitId = button.dataset.removeVisit;
    const recipientId = button.dataset.removeRecipient;
    const item = visits.find((visit) => visit.id === visitId);
    if (!visitId || !recipientId || !item || !["active", "stopped", "expired"].includes(item.state)
      || item.recipients.length <= 1) return;
    if (blockNavigationWithUnsavedChanges()) return;
    const removalKey = `${visitId}\u0000${recipientId}`;
    if (pendingRecipientRemovals.has(removalKey)) return;
    pendingRecipientRemovals.add(removalKey);
    message = "正在移除通知對象…";
    renderDashboard();
    try {
      await removeVisitRecipient(visitId, recipientId);
      message = "已移除通知對象。";
    } catch (error) {
      message = errorText(error);
    } finally {
      pendingRecipientRemovals.delete(removalKey);
      await loadDashboard();
    }
  }));

  void maybeFetchRoster();
}

void loadDashboard();

export { canRequestStart, readForm };
