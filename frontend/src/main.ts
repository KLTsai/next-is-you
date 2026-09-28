import "./style.css";
import { canStartVisit, formatStatus, isFreshMatchingObservation } from "./visit-state.js";

type Hospital = "ntuh-main" | "shin-kong-taipei";
type VisitStatus = "draft" | "active" | "stopping" | "stopped" | "source-unavailable" | "terminal";

interface VisitView {
  id: string;
  status: VisitStatus;
  hospital: Hospital;
  hospitalName: string;
  visitDate: string;
  departmentCode: string | null;
  clinicCode: string | null;
  session: string | null;
  doctorCode: string | null;
  roomCode: string | null;
  sourceUrl: string | null;
  recipients: string[];
  latestCheck: string | null;
  observation: { hospital: Hospital; visitDate: string; departmentCode: string | null; clinicCode: string | null; session: string | null; currentNumber: number | null; nextNumber: number | null; callType: string | null; trustworthy: boolean; observedAt: string } | null;
  sendResult: string | null;
}

const app = document.querySelector<HTMLElement>("#app");
const serviceStatus = document.querySelector<HTMLSpanElement>("#service-status");
const hospitalNames: Record<Hospital, string> = {
  "ntuh-main": "臺大醫院總院",
  "shin-kong-taipei": "新光醫院（台北）",
};
let visit: VisitView | null = null;
let catalogMessage = "目前沒有可用的院方診次資料。";

function text(value: string | null | undefined): string {
  return value || "尚無資料";
}

function renderVisit(item: VisitView): string {
  const status = formatStatus(item.status);
  const active = item.status === "active";
  return `<article class="visit-card" aria-labelledby="visit-title">
    <div class="visit-heading"><div><p class="eyebrow">看診提醒</p><h3 id="visit-title">${item.hospitalName}・${item.visitDate}</h3></div><span class="state state-${item.status}">${status}</span></div>
    ${item.status === "draft" ? `<div class="notice" role="status"><strong>草稿尚未啟動</strong><p>尚未取得可核對的院方診次資料。請確認醫院與日期；診間及診次只會在來源提供時列出。</p></div>` : ""}
    ${item.status === "source-unavailable" ? `<div class="notice" role="status"><strong>院方來源目前無法使用</strong><p>提醒保持草稿狀態。恢復可用且核對正確的資料後，才能重新檢查。</p></div>` : ""}
    <dl class="details">
      <div><dt>科別・診間・診次</dt><dd>${[item.departmentCode, item.clinicCode, item.session].filter(Boolean).map(text).join("・") || "尚未選定"}</dd></div>
      <div><dt>醫師・診間名稱</dt><dd>${[item.doctorCode, item.roomCode].filter(Boolean).map(text).join("・") || "尚無來源資料"}</dd></div>
      <div><dt>院方資料來源</dt><dd>${safeSourceUrl(item.sourceUrl) ? `<a href="${escapeHtml(safeSourceUrl(item.sourceUrl) as string)}" target="_blank" rel="noreferrer">開啟院方來源</a>` : "來源連結尚未提供"}</dd></div>
      <div><dt>通知對象</dt><dd>${item.recipients.length ? item.recipients.map(escapeHtml).join("、") : "尚未選擇；可用名單未連接"}</dd></div>
      <div><dt>最近檢查</dt><dd>${text(item.latestCheck)}</dd></div>
      <div><dt>院方觀察</dt><dd>${item.observation ? `目前號碼 ${text(String(item.observation.currentNumber))} ・ 下一號 ${text(String(item.observation.nextNumber))} ・ ${text(item.observation.callType)} ・ ${item.observation.trustworthy ? "已驗證" : "未驗證"}` : "尚無可信觀察資料"}</dd></div>
      <div><dt>訊息傳送結果</dt><dd>${text(item.sendResult)}</dd></div>
    </dl>
    ${active ? `<div class="stop-row"><p>監控中。你可以隨時停止提醒。</p><button class="stop-button" type="button" data-stop="${escapeHtml(item.id)}">停止提醒</button></div>` : ""}
    ${item.status === "stopping" ? `<p class="inline-state" role="status">正在停止提醒…</p>` : ""}
    ${item.status === "stopped" ? `<p class="inline-state" role="status">提醒已停止。</p>` : ""}
    ${item.status === "terminal" ? `<p class="inline-state" role="status">此提醒已結束，不能再次啟動。</p>` : ""}
  </article>`;
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char] || char);
}

function safeSourceUrl(value: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}

function render(): void {
  if (!app) return;
  app.innerHTML = `<section class="panel" aria-labelledby="setup-heading">
    <div class="panel-heading"><div><p class="eyebrow">新的候診提醒</p><h2 id="setup-heading">設定看診資料</h2></div><span class="step-count">草稿</span></div>
    <p class="intro">先選醫院與日期。只有院方來源實際提供、且能完整核對的診次才會出現；資料不足時不會啟動提醒。</p>
    <fieldset class="hospital-options"><legend>醫院</legend>
      <label class="choice"><input type="radio" name="hospital" value="ntuh-main" ${!visit || visit.hospital === "ntuh-main" ? "checked" : ""}><span>臺大醫院總院</span></label>
      <label class="choice"><input type="radio" name="hospital" value="shin-kong-taipei" ${visit?.hospital === "shin-kong-taipei" ? "checked" : ""}><span>新光醫院（台北）</span></label>
    </fieldset>
    <label class="field" for="visit-date"><span>看診日期</span><input id="visit-date" name="visit-date" type="date" value="${visit ? escapeHtml(visit.visitDate) : ""}"></label>
    <section class="source-panel" aria-live="polite"><div class="source-heading"><div><p class="eyebrow">可選診次</p><h3>院方診次資料不可用</h3></div><span class="state state-source-unavailable">來源 unavailable</span></div><p>${escapeHtml(catalogMessage)}</p><p class="source-link">院方來源連結：尚未提供</p></section>
    <fieldset class="recipient-panel"><legend>通知對象</legend><p>尚未連接已同意接收提醒的對象名單，目前無法選擇通知對象。</p></fieldset>
    <div class="action-row"><button id="save-draft" class="secondary-button" type="button">${visit ? "更新草稿" : "建立草稿"}</button><button id="start-visit" class="primary-button" type="button" ${visit && canStartVisit(visit) ? "" : "disabled"}>開始提醒</button></div>
    <p class="gate-note" id="gate-note" role="status">開始提醒需要新鮮、可信且符合醫院、日期、科別、診間與診次的院方觀察。目前沒有符合條件的觀察。</p>
  </section>
  <section class="visits" aria-labelledby="visits-heading"><div class="section-heading"><div><p class="eyebrow">狀態與控制</p><h2 id="visits-heading">提醒狀態</h2></div></div>${visit ? renderVisit(visit) : `<div class="empty-state"><span class="empty-icon" aria-hidden="true">—</span><h3>尚無提醒</h3><p>建立草稿後，這裡會顯示狀態、來源、通知對象、最近檢查、叫號觀察與傳送結果。</p></div>`}</section>`;
  bindActions();
}

function bindActions(): void {
  const createButton = document.querySelector<HTMLButtonElement>("#save-draft");
  createButton?.addEventListener("click", () => {
    const selected = document.querySelector<HTMLInputElement>('input[name="hospital"]:checked');
    const date = document.querySelector<HTMLInputElement>("#visit-date")?.value;
    if (!selected || !date) {
      document.querySelector<HTMLElement>("#gate-note")!.textContent = "請先選擇醫院與看診日期，再建立草稿。";
      return;
    }
    visit = {
      id: "local-draft", status: "draft", hospital: selected.value as Hospital,
      hospitalName: hospitalNames[selected.value as Hospital], visitDate: date,
      departmentCode: null, clinicCode: null, session: null, doctorCode: null,
      roomCode: null, sourceUrl: null, recipients: [], latestCheck: null,
      observation: null, sendResult: null,
    };
    render();
  });

  document.querySelector<HTMLButtonElement>("#start-visit")?.addEventListener("click", () => {
    const note = document.querySelector<HTMLElement>("#gate-note");
    if (!visit || !isFreshMatchingObservation(visit.observation, {
      hospital: visit.hospital, visitDate: visit.visitDate,
      departmentCode: visit.departmentCode, clinicCode: visit.clinicCode, session: visit.session,
    })) {
      if (note) note.textContent = "目前觀察無法與完整看診資料核對，提醒維持草稿。";
      return;
    }
    if (note) note.textContent = "啟動功能尚未連接本機服務，提醒仍維持草稿。";
  });

  document.querySelector<HTMLButtonElement>("[data-stop]")?.addEventListener("click", async () => {
    if (!visit || visit.status !== "active") return;
    visit.status = "stopping";
    render();
    try {
      const csrfCookie = document.cookie.split(";").map((cookie) => cookie.trim()).find((cookie) => cookie.startsWith("__Host-ny_csrf="));
      const csrfToken = csrfCookie?.slice("__Host-ny_csrf=".length);
      const response = await fetch(`/api/visits/${encodeURIComponent(visit.id)}/stop`, {
        method: "POST",
        headers: csrfToken ? { "x-csrf-token": decodeURIComponent(csrfToken) } : {},
      });
      if (!response.ok) throw new Error("stop request failed");
      const result: { state?: string } = await response.json();
      if (result.state !== "stopping" && result.state !== "stopped") throw new Error("stop response had no terminal state");
      visit.status = result.state;
    } catch {
      visit.status = "active";
      const note = document.querySelector<HTMLElement>(".stop-row p");
      if (note) note.textContent = "停止請求未完成，提醒仍在監控中；請再試一次。";
    }
    render();
  });
}

async function loadAvailability(): Promise<void> {
  if (!serviceStatus) return;
  try {
    const response = await fetch("/api/healthz", { headers: { accept: "application/json" } });
    if (!response.ok) throw new Error("health check failed");
    serviceStatus.textContent = "本機服務正常";
    serviceStatus.className = "status status-ok";
    const catalog = await fetch("/api/clinics", { headers: { accept: "application/json" } });
    if (catalog.ok) {
      const data: unknown = await catalog.json();
      if (!Array.isArray(data) || data.length > 0) {
        catalogMessage = "診次資料格式尚未支援，為避免選錯診次，暫不提供選項。";
      }
    }
  } catch {
    serviceStatus.textContent = "院方資料 unavailable";
    serviceStatus.className = "status status-pending";
    catalogMessage = "本機服務或診次目錄目前無法使用。草稿仍可保留在此畫面，提醒不會啟動。";
  }
  render();
}

void loadAvailability();
render();

export { canStartVisit };
