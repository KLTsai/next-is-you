import "./style.css";
import {
  OrganizerApiError,
  correctVisit,
  createVisit,
  listRecipients,
  listVisits,
  startVisit,
  stopVisit,
  updateVisit,
} from "./organizer-api.js";
import type { Hospital, OrganizerVisit, Recipient, VisitInput } from "./organizer-api.js";
import { canRequestStart, formatSourceStatus, formatVisitState, visitStatusKey } from "./visit-state.js";
import { sourceLinkMarkup } from "./source-link.js";

const app = document.querySelector<HTMLElement>("#app");
const serviceStatus = document.querySelector<HTMLSpanElement>("#service-status");
const hospitalNames: Record<Hospital, string> = {
  "ntuh-main": "臺大醫院總院",
  "shin-kong-taipei": "新光醫院（台北）",
};
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
let authorized = false;
let loading = false;
let message = "";
let editing: { visit: OrganizerVisit; mode: "update" | "correct" } | null = null;
let formValues: Record<string, string | string[]> | null = null;
let discardFormOnNextRender = false;
const pendingStops = new Set<string>();
const pendingStarts = new Set<string>();

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char] || char);
}

function text(value: string | number | null | undefined): string {
  return value === null || value === undefined || value === "" ? "尚無資料" : String(value);
}

function errorText(error: unknown): string {
  if (!(error instanceof OrganizerApiError)) return "連線失敗，請確認本機服務後重試。";
  const labels: Record<string, string> = {
    service_unavailable: "目前無法使用提醒服務。",
    invalid_request: "資料不完整或格式不正確，請檢查後再試。",
    ineligible_recipients: "通知對象已無法接收提醒，請重新選擇。",
    invalid_lifecycle_state: "提醒狀態已變更，請重新載入。",
    observation_unavailable: "目前沒有可用的可信院方觀察，提醒維持草稿。",
    observation_stale: "院方觀察已過期，提醒維持草稿。",
    observation_scope_mismatch: "院方觀察與所選診次不符，提醒維持草稿。",
    observation_untrusted: "院方資料尚未通過可信度檢查，提醒維持草稿。",
    observation_invalid: "院方資料無效，提醒維持草稿。",
    scheduler_held: "排程暫停中，提醒維持草稿。",
    visit_not_found: "找不到這筆提醒，請重新載入。",
  };
  if (error.status === 401 || error.status === 403) return "登入已失效或目前帳號沒有管理權限。";
  return labels[error.code] || "操作未完成，請重新載入後再試。";
}

function renderLogin(): string {
  return `<section class="panel login-panel" aria-labelledby="login-heading">
    <p class="eyebrow">管理者登入</p><h1 id="login-heading">登入以管理家人提醒</h1>
    <p class="intro">只有已授權的管理者能查看或修改提醒。請使用已設定的 LINE Login，或在明確啟用 NIY-006 本機測試設定時使用合成測試登入。</p>
    ${message ? `<p class="message message-warning" role="status">${escapeHtml(message)}</p>` : ""}
    <div class="login-actions"><a class="primary-button link-button" href="/auth/line">使用 LINE Login</a><button class="secondary-button" id="synthetic-login" type="button">本機合成測試登入</button></div>
    <p class="gate-note">合成測試登入只在 NIY006_LOCAL_TEST_MODE 明確啟用的本機綁定中有效，不會呼叫 LINE。</p>
  </section>`;
}

function recipientChoices(selected: string[]): string {
  if (!recipients.length) return `<p class="empty-inline">目前沒有已同意且可用的通知對象。</p>`;
  return recipients.map((recipient) => `<label class="recipient-choice"><input type="checkbox" name="recipient_ids" value="${escapeHtml(recipient.id)}" ${selected.includes(recipient.id) ? "checked" : ""}><span>${escapeHtml(recipient.display_name)}</span></label>`).join("");
}

function rememberFormValues(): void {
  const form = document.querySelector<HTMLFormElement>("#visit-form");
  if (!form) return;
  const data = new FormData(form);
  formValues = {
    hospital: String(data.get("hospital") ?? "ntuh-main"),
    date: String(data.get("date") ?? ""),
    patient_number: String(data.get("patient_number") ?? ""),
    department_code: String(data.get("department_code") ?? ""),
    clinic_code: String(data.get("clinic_code") ?? ""),
    session: String(data.get("session") ?? "morning"),
    recipient_ids: data.getAll("recipient_ids").map(String),
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
  const saved = editing?.visit;
  const baselineRecipients = saved?.recipients.map((recipient) => recipient.id).sort() ?? [];
  const currentRecipients = data.getAll("recipient_ids").map(String).sort();
  return data.get("hospital") !== (saved?.hospital ?? "ntuh-main")
    || data.get("date") !== (saved?.date ?? "")
    || data.get("patient_number") !== ""
    || data.get("department_code") !== (saved?.department_code ?? "")
    || data.get("clinic_code") !== (saved?.clinic_code ?? "")
    || data.get("session") !== (saved?.session ?? "morning")
    || currentRecipients.join("\u0000") !== baselineRecipients.join("\u0000");
}

function blockNavigationWithUnsavedChanges(): boolean {
  if (!hasUnsavedFormChanges()) return false;
  message = "目前設定尚未儲存。請先儲存或取消修正，再開啟其他提醒。";
  renderDashboard();
  return true;
}

function formMarkup(): string {
  const item = editing?.visit;
  const storedRecipients = item?.recipients.map((recipient) => recipient.id) ?? [];
  const draftRecipients = formValues?.recipient_ids;
  const selectedRecipients = Array.isArray(draftRecipients) ? draftRecipients : storedRecipients;
  const defaultHospital = formValue("hospital", item?.hospital ?? "ntuh-main");
  const formTitle = editing?.mode === "correct" ? "修正已停止的提醒" : item ? "修正草稿" : "建立候診提醒";
  const submitLabel = editing?.mode === "correct" ? "儲存修正並回到草稿" : item ? "儲存草稿" : "建立草稿";
  return `<section class="panel" aria-labelledby="setup-heading">
    <div class="panel-heading"><div><p class="eyebrow">提醒設定</p><h2 id="setup-heading">${formTitle}</h2></div><span class="step-count">${item ? formatVisitState(item.state) : "新草稿"}</span></div>
    ${item ? `<p class="edit-notice" role="status">你正在修改已儲存的${editing?.mode === "correct" ? "已停止提醒" : "草稿"}。畫面上的變更尚未儲存；取消會捨棄這次編輯，儲存後仍須重新檢查才能開始提醒。</p>` : `<p class="intro">先建立草稿，再由提醒清單檢查並開始。建立或儲存草稿不會啟動監控，也不會傳送通知。</p>`}
    <form id="visit-form" novalidate>
      <fieldset class="hospital-options"><legend>醫院</legend>
        <label class="choice"><input type="radio" name="hospital" value="ntuh-main" ${defaultHospital === "ntuh-main" ? "checked" : ""} required><span>臺大醫院總院</span></label>
        <label class="choice"><input type="radio" name="hospital" value="shin-kong-taipei" ${defaultHospital === "shin-kong-taipei" ? "checked" : ""}><span>新光醫院（台北）</span></label>
      </fieldset>
      <div class="form-grid">
        <label class="field"><span>看診日期</span><input name="date" type="date" value="${escapeHtml(formValue("date", item?.date ?? ""))}" required></label>
        <label class="field"><span>掛號序號</span><input name="patient_number" type="number" min="1" max="999999" value="${escapeHtml(formValue("patient_number", ""))}" required inputmode="numeric"><small>${item ? "目前 API 不會回傳已儲存的掛號序號，請對照院方資料填入。" : "僅供這筆提醒使用，不會顯示在狀態清單。"}</small></label>
        <label class="field"><span>科別代碼</span><input name="department_code" maxlength="64" value="${escapeHtml(formValue("department_code", item?.department_code ?? ""))}" required autocomplete="off"></label>
        <label class="field"><span>診間代碼</span><input name="clinic_code" maxlength="64" value="${escapeHtml(formValue("clinic_code", item?.clinic_code ?? ""))}" required autocomplete="off"></label>
        <label class="field"><span>診次</span><select name="session" required>
          <option value="morning" ${formValue("session", item?.session ?? "morning") === "morning" ? "selected" : ""}>${sessionNames.morning}（morning）</option>
          <option value="afternoon" ${formValue("session", item?.session ?? "morning") === "afternoon" ? "selected" : ""}>${sessionNames.afternoon}（afternoon）</option>
          <option value="evening" ${formValue("session", item?.session ?? "morning") === "evening" ? "selected" : ""}>${sessionNames.evening}（evening）</option>
        </select><small>這是系統目前接受的診次代碼，不代表該院、該科別或日期有開診。請先依院方資訊確認；API 尚未提供診間與日期的可選診次。</small></label>
      </div>
      <fieldset class="recipient-panel"><legend>通知對象</legend><div class="recipient-list">${recipientChoices(selectedRecipients)}</div></fieldset>
      <div class="action-row"><button class="primary-button" type="submit">${submitLabel}</button>${item ? `<button class="secondary-button" id="cancel-edit" type="button">取消修正</button>` : ""}</div>
    </form>
    <p class="gate-note">儲存只會建立或更新草稿。提醒清單會顯示 API 提供的院方官方來源連結；連結不代表已查詢院方資料。</p>
  </section>`;
}

function visitCard(item: OrganizerVisit): string {
  const stateKey = visitStatusKey(item);
  const active = item.state === "active";
  const pendingStop = pendingStops.has(item.id);
  const pendingStart = pendingStarts.has(item.id);
  const recipientsText = item.recipients.length
    ? item.recipients.map((recipient) => escapeHtml(recipient.display_name)).join("、")
    : "沒有選取通知對象";
  const notification = item.notification;
  const sourceStatus = item.source_read?.status ?? "unavailable";
  const sourceReason = sourceReasons[item.source_read?.reason] ?? "來源狀態尚未提供";
  return `<article class="visit-card" aria-labelledby="visit-${escapeHtml(item.id)}">
    <div class="visit-heading"><div><p class="eyebrow">${escapeHtml(hospitalNames[item.hospital] ?? item.hospital)}</p><h3 id="visit-${escapeHtml(item.id)}">${escapeHtml(item.date)} · ${escapeHtml(item.department_code)} · ${escapeHtml(item.clinic_code)}</h3><p class="visit-session">${escapeHtml(sessionNames[item.session])}（${escapeHtml(item.session)}）</p></div><span class="state state-${stateKey}">${stateKey === "source-unavailable" ? "來源 unavailable · 草稿" : stateKey === "terminal" ? "已結束" : formatVisitState(item.state)}</span></div>
    <dl class="details">
      <div><dt>科別・診間・診次</dt><dd>${escapeHtml(item.department_code)}・${escapeHtml(item.clinic_code)}・${escapeHtml(item.session)}</dd></div>
      <div><dt>院方資料來源</dt><dd>${sourceLinkMarkup(item.source_url)}</dd></div>
      <div><dt>通知對象</dt><dd>${recipientsText}</dd></div>
      <div><dt>最近檢查</dt><dd>${escapeHtml(text(item.observation?.checked_at))}</dd></div>
      <div><dt>院方觀察</dt><dd>${item.observation?.current_number ? `目前號碼 ${escapeHtml(String(item.observation.current_number))}` : "尚無可用的號碼觀察"}</dd></div>
      <div><dt>來源狀態</dt><dd>${escapeHtml(formatSourceStatus(sourceStatus))} · ${escapeHtml(sourceReason)}</dd></div>
      <div><dt>訊息傳送結果</dt><dd>共 ${notification.count} 則；已接受 ${notification.accepted} 則；需留意 ${notification.issues} 則</dd></div>
    </dl>
    ${active ? `<div class="stop-row"><div><p>${pendingStop ? "停止請求處理中…" : "監控中。停止確認後，系統會停止後續檢查與通知。"}</p><small>停止完成前，狀態仍以服務回覆為準。</small></div><button class="stop-button" type="button" data-stop="${escapeHtml(item.id)}" ${pendingStop ? "disabled" : ""}>${pendingStop ? "停止中" : "停止提醒"}</button></div>` : ""}
    ${item.state === "stopping" ? `<p class="inline-state" role="status">停止已送出，正在等候關閉確認。</p>` : ""}
    ${item.state === "stopped" ? `<p class="inline-state" role="status">提醒已停止。</p>` : ""}
    ${item.state === "expired" ? `<p class="inline-state" role="status">此提醒已結束，不能再次啟動。</p>` : ""}
    ${pendingStart ? `<p class="inline-state" role="status">正在檢查可信院方觀察…</p>` : ""}
    <div class="visit-actions">
      ${item.state === "draft" ? `<button class="secondary-button" type="button" data-edit="${escapeHtml(item.id)}">修正草稿</button><button class="primary-button" type="button" data-start="${escapeHtml(item.id)}" ${canRequestStart(item) && !pendingStart && editing?.visit.id !== item.id ? "" : "disabled"}>${pendingStart ? "重新檢查中…" : "重新檢查並開始提醒"}</button>` : ""}
      ${item.state === "stopped" ? `<button class="secondary-button" type="button" data-correct="${escapeHtml(item.id)}">修正後重新檢查</button>` : ""}
    </div>
    ${item.state === "draft" && editing?.visit.id === item.id ? `<p class="gate-note">清單仍顯示已儲存的草稿。先儲存或取消修正，再重新檢查並開始。</p>` : item.state === "draft" && !canRequestStart(item) ? `<p class="gate-note">開始前請填妥醫院、日期、科別、診間、診次，並選擇至少一位通知對象。</p>` : item.state === "draft" ? `<p class="gate-note">服務會重新檢查來源資料。只有取得新鮮、可信且完全符合診次的觀察後，服務才會回覆啟動成功；失敗時維持草稿。</p>` : ""}
  </article>`;
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
  app.innerHTML = `<div class="dashboard-top"><div><p class="eyebrow">安全的提醒管理</p><h1>看診提醒</h1></div><button class="secondary-button refresh-button" id="refresh" type="button" ${loading ? "disabled" : ""}>重新整理</button></div>
    ${message ? `<p class="message" role="status">${escapeHtml(message)}</p>` : ""}
    ${formMarkup()}
    <section class="visits" aria-labelledby="visits-heading"><div class="section-heading"><div><p class="eyebrow">狀態與控制</p><h2 id="visits-heading">提醒清單</h2></div></div>${visits.length ? visits.map(visitCard).join("") : `<div class="empty-state"><span class="empty-icon" aria-hidden="true">-</span><h3>尚無提醒</h3><p>建立草稿後，這裡會顯示狀態、來源、通知對象、最近檢查、院方觀察與傳送結果。</p></div>`}</section>`;
  bindActions();
}

async function loadDashboard(): Promise<void> {
  if (!serviceStatus) return;
  loading = true;
  try {
    const health = await fetch("/api/healthz", { headers: { accept: "application/json" } });
    if (!health.ok) throw new Error("service unavailable");
    serviceStatus.textContent = "本機服務正常";
    serviceStatus.className = "status status-ok";
    const [roster, projection] = await Promise.all([listRecipients(), listVisits()]);
    recipients = roster.recipients;
    visits = projection.visits;
    authorized = true;
  } catch (error) {
    if (error instanceof OrganizerApiError && (error.status === 401 || error.status === 403)) {
      authorized = false;
      message = "請登入已授權的管理者帳號。";
    } else {
      authorized = false;
      serviceStatus.textContent = "本機服務不可用";
      serviceStatus.className = "status status-pending";
      message = errorText(error);
    }
  } finally {
    loading = false;
    renderDashboard();
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
  if ((hospital !== "ntuh-main" && hospital !== "shin-kong-taipei") || typeof date !== "string" || !date
    || typeof department !== "string" || !department.trim() || typeof clinic !== "string" || !clinic.trim()
    || (session !== "morning" && session !== "afternoon" && session !== "evening")
    || !Number.isSafeInteger(patientNumber) || patientNumber < 1 || selectedRecipients.length === 0) return null;
  return {
    hospital, date, department_code: department.trim(), clinic_code: clinic.trim(),
    session, patient_number: patientNumber, recipient_ids: selectedRecipients,
  };
}

function bindActions(): void {
  document.querySelector<HTMLButtonElement>("#refresh")?.addEventListener("click", () => {
    message = "";
    void loadDashboard();
  });
  document.querySelector<HTMLButtonElement>("#cancel-edit")?.addEventListener("click", () => {
    editing = null;
    formValues = null;
    message = "";
    renderDashboard(false);
  });
  document.querySelector<HTMLFormElement>("#visit-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    if (!(form instanceof HTMLFormElement)) return;
    if (!form.reportValidity()) return;
    const input = readForm(form);
    if (!input) {
      message = "請輸入完整診次資料並選擇至少一位通知對象。";
      renderDashboard();
      return;
    }
    try {
      const previous = editing;
      if (!previous) await createVisit(input);
      else if (previous.mode === "correct") await correctVisit(previous.visit.id, input);
      else await updateVisit(previous.visit.id, input);
      editing = null;
      formValues = null;
      discardFormOnNextRender = true;
      message = previous?.mode === "correct"
        ? "修正已儲存為草稿。請在提醒清單重新檢查並開始。"
        : previous ? "草稿修改已儲存。請在提醒清單重新檢查並開始。"
          : "草稿已建立。建立草稿不會啟動監控或傳送通知。";
      await loadDashboard();
    } catch (error) {
      message = errorText(error);
      renderDashboard();
    }
  });

  document.querySelectorAll<HTMLButtonElement>("[data-edit]").forEach((button) => button.addEventListener("click", () => {
    const item = visits.find((visit) => visit.id === button.dataset.edit);
    if (!item) return;
    if (blockNavigationWithUnsavedChanges()) return;
    formValues = null;
    editing = { visit: item, mode: "update" };
    message = "";
    renderDashboard(false);
    document.querySelector("#setup-heading")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }));
  document.querySelectorAll<HTMLButtonElement>("[data-correct]").forEach((button) => button.addEventListener("click", () => {
    const item = visits.find((visit) => visit.id === button.dataset.correct);
    if (!item) return;
    if (blockNavigationWithUnsavedChanges()) return;
    formValues = null;
    editing = { visit: item, mode: "correct" };
    message = "";
    renderDashboard(false);
    document.querySelector("#setup-heading")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }));
  document.querySelectorAll<HTMLButtonElement>("[data-start]").forEach((button) => button.addEventListener("click", async () => {
    const id = button.dataset.start;
    const item = visits.find((visit) => visit.id === id);
    if (!id || !item || !canRequestStart(item)) return;
    pendingStarts.add(id);
    message = "";
    renderDashboard();
    try {
      const result = await startVisit(id);
      message = result.state === "active" ? "服務已回覆啟動成功。" : "服務尚未確認啟動，請查看清單狀態。";
    } catch (error) {
      message = errorText(error);
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
      message = result.state === "stopped" ? "提醒已停止。" : "停止請求已送出，正在等候關閉確認。";
    } catch (error) {
      message = errorText(error);
    } finally {
      pendingStops.delete(id);
      await loadDashboard();
    }
  }));
}

void loadDashboard();

export { canRequestStart, readForm };
