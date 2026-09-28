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

function formMarkup(): string {
  const item = editing?.visit;
  const selectedRecipients = item?.recipients.map((recipient) => recipient.id) ?? [];
  const defaultHospital = item?.hospital ?? "ntuh-main";
  const formTitle = editing?.mode === "correct" ? "修正已停止的提醒" : item ? "修正草稿" : "建立候診提醒";
  const submitLabel = editing?.mode === "correct" ? "儲存修正" : item ? "儲存草稿" : "建立草稿";
  return `<section class="panel" aria-labelledby="setup-heading">
    <div class="panel-heading"><div><p class="eyebrow">提醒設定</p><h2 id="setup-heading">${formTitle}</h2></div><span class="step-count">${item ? formatVisitState(item.state) : "新草稿"}</span></div>
    <p class="intro">診間與診次不會由畫面自行推測。請只輸入院方資料已提供的診次；目前沒有可用的院方診次目錄，因此提醒會保持草稿，直到來源回報可信且完全相符的觀察。</p>
    <form id="visit-form" novalidate>
      <fieldset class="hospital-options"><legend>醫院</legend>
        <label class="choice"><input type="radio" name="hospital" value="ntuh-main" ${defaultHospital === "ntuh-main" ? "checked" : ""} required><span>臺大醫院總院</span></label>
        <label class="choice"><input type="radio" name="hospital" value="shin-kong-taipei" ${defaultHospital === "shin-kong-taipei" ? "checked" : ""}><span>新光醫院（台北）</span></label>
      </fieldset>
      <div class="form-grid">
        <label class="field"><span>看診日期</span><input name="date" type="date" value="${escapeHtml(item?.date ?? "")}" required></label>
        <label class="field"><span>掛號序號</span><input name="patient_number" type="number" min="1" max="999999" value="" required inputmode="numeric"><small>${item ? "請重新輸入掛號序號以修正草稿。" : "僅供這筆提醒使用，不會顯示在狀態清單。"}</small></label>
        <label class="field"><span>科別代碼</span><input name="department_code" maxlength="64" value="${escapeHtml(item?.department_code ?? "")}" required autocomplete="off"></label>
        <label class="field"><span>診間代碼</span><input name="clinic_code" maxlength="64" value="${escapeHtml(item?.clinic_code ?? "")}" required autocomplete="off"></label>
        <label class="field"><span>診次代碼</span><input name="session" value="${escapeHtml(item?.session ?? "")}" pattern="morning|afternoon|evening" required autocomplete="off"><small>請依院方提供的代碼輸入；目前沒有依醫院、日期及診間核對過的診次目錄，因此不列出通用選項。</small></label>
      </div>
      <fieldset class="recipient-panel"><legend>通知對象</legend><div class="recipient-list">${recipientChoices(selectedRecipients)}</div></fieldset>
      <div class="action-row"><button class="primary-button" type="submit">${submitLabel}</button>${item ? `<button class="secondary-button" id="cancel-edit" type="button">取消修正</button>` : ""}</div>
    </form>
    ${message ? `<p class="message" role="status">${escapeHtml(message)}</p>` : ""}
    <p class="gate-note">提醒清單會顯示 API 提供的院方官方來源連結。診次目錄尚未提供，請只輸入院方已提供的診次資料。</p>
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
    <div class="visit-heading"><div><p class="eyebrow">${escapeHtml(hospitalNames[item.hospital] ?? item.hospital)}</p><h3 id="visit-${escapeHtml(item.id)}">${escapeHtml(item.date)} · ${escapeHtml(item.department_code)} · ${escapeHtml(item.clinic_code)}</h3><p class="visit-session">${escapeHtml(item.session)}</p></div><span class="state state-${stateKey}">${stateKey === "source-unavailable" ? "來源 unavailable · 草稿" : stateKey === "terminal" ? "已結束" : formatVisitState(item.state)}</span></div>
    <dl class="details">
      <div><dt>科別・診間・診次</dt><dd>${escapeHtml(item.department_code)}・${escapeHtml(item.clinic_code)}・${escapeHtml(item.session)}</dd></div>
      <div><dt>院方資料來源</dt><dd>${sourceLinkMarkup(item.source_url)}</dd></div>
      <div><dt>通知對象</dt><dd>${recipientsText}</dd></div>
      <div><dt>最近檢查</dt><dd>${escapeHtml(text(item.observation?.checked_at))}</dd></div>
      <div><dt>院方觀察</dt><dd>${item.observation?.current_number ? `目前號碼 ${escapeHtml(String(item.observation.current_number))}` : "尚無可用的號碼觀察"}</dd></div>
      <div><dt>來源狀態</dt><dd>${escapeHtml(formatSourceStatus(sourceStatus))} · ${escapeHtml(sourceReason)}</dd></div>
      <div><dt>訊息傳送結果</dt><dd>共 ${notification.count} 則；已接受 ${notification.accepted} 則；需留意 ${notification.issues} 則</dd></div>
    </dl>
    ${active ? `<div class="stop-row"><p>${pendingStop ? "停止請求處理中…" : "監控中。你可以隨時停止提醒。"}</p><button class="stop-button" type="button" data-stop="${escapeHtml(item.id)}" ${pendingStop ? "disabled" : ""}>${pendingStop ? "停止中" : "停止提醒"}</button></div>` : ""}
    ${item.state === "stopping" ? `<p class="inline-state" role="status">停止已送出，正在等候關閉確認。</p>` : ""}
    ${item.state === "stopped" ? `<p class="inline-state" role="status">提醒已停止。</p>` : ""}
    ${item.state === "expired" ? `<p class="inline-state" role="status">此提醒已結束，不能再次啟動。</p>` : ""}
    ${pendingStart ? `<p class="inline-state" role="status">正在檢查可信院方觀察…</p>` : ""}
    <div class="visit-actions">
      ${item.state === "draft" ? `<button class="secondary-button" type="button" data-edit="${escapeHtml(item.id)}">修正草稿</button><button class="primary-button" type="button" data-start="${escapeHtml(item.id)}" ${canRequestStart(item) && !pendingStart ? "" : "disabled"}>${sourceStatus === "usable" ? "開始提醒" : "檢查資料並開始"}</button>` : ""}
      ${item.state === "stopped" ? `<button class="secondary-button" type="button" data-correct="${escapeHtml(item.id)}">修正後重新檢查</button>` : ""}
    </div>
    ${item.state === "draft" && !canRequestStart(item) ? `<p class="gate-note">開始前請填妥醫院、日期、科別、診間、診次，並選擇至少一位通知對象。</p>` : item.state === "draft" && sourceStatus !== "usable" ? `<p class="gate-note">來源目前尚未核對。開始請求會由本機服務重新檢查；沒有新鮮、可信且完全相符的觀察時，提醒會維持草稿。</p>` : ""}
  </article>`;
}

function renderDashboard(): void {
  if (!app) return;
  if (!authorized) {
    app.innerHTML = renderLogin();
    document.querySelector<HTMLButtonElement>("#synthetic-login")?.addEventListener("click", voidSyntheticLogin);
    return;
  }
  app.innerHTML = `<div class="dashboard-top"><div><p class="eyebrow">安全的提醒管理</p><h1>看診提醒</h1></div><button class="secondary-button refresh-button" id="refresh" type="button" ${loading ? "disabled" : ""}>重新整理</button></div>
    ${message ? `<p class="message" role="status">${escapeHtml(message)}</p>` : ""}
    ${formMarkup()}
    <section class="visits" aria-labelledby="visits-heading"><div class="section-heading"><div><p class="eyebrow">狀態與控制</p><h2 id="visits-heading">提醒清單</h2></div></div>${visits.length ? visits.map(visitCard).join("") : `<div class="empty-state"><span class="empty-icon" aria-hidden="true">—</span><h3>尚無提醒</h3><p>建立草稿後，這裡會顯示狀態、來源、通知對象、最近檢查、院方觀察與傳送結果。</p></div>`}</section>`;
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
    message = "";
    renderDashboard();
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
      if (!editing) await createVisit(input);
      else if (editing.mode === "correct") await correctVisit(editing.visit.id, input);
      else await updateVisit(editing.visit.id, input);
      editing = null;
      message = "草稿已儲存。來源未核對前不會啟動提醒。";
      await loadDashboard();
    } catch (error) {
      message = errorText(error);
      renderDashboard();
    }
  });

  document.querySelectorAll<HTMLButtonElement>("[data-edit]").forEach((button) => button.addEventListener("click", () => {
    const item = visits.find((visit) => visit.id === button.dataset.edit);
    if (!item) return;
    editing = { visit: item, mode: "update" };
    message = "";
    renderDashboard();
    document.querySelector("#setup-heading")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }));
  document.querySelectorAll<HTMLButtonElement>("[data-correct]").forEach((button) => button.addEventListener("click", () => {
    const item = visits.find((visit) => visit.id === button.dataset.correct);
    if (!item) return;
    editing = { visit: item, mode: "correct" };
    message = "";
    renderDashboard();
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
      await startVisit(id);
      message = "提醒已啟動。";
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
