import "./style.css";

const app = document.querySelector<HTMLElement>("#consent-app");

type ConsentState = "idle" | "submitting" | "joined" | "error";

let state: ConsentState = "idle";
let errorMessage = "";

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char] || char);
}

function csrfFromCookie(): string {
  const item = document.cookie.split(";").map((cookie) => cookie.trim())
    .find((cookie) => cookie.startsWith("__Host-ny_csrf="));
  return item ? decodeURIComponent(item.slice("__Host-ny_csrf=".length)) : "";
}

function errorTextFor(status: number): string {
  if (status === 409) return "這個帳號已經加入過，或目前無法完成確認。可以關閉這個頁面了。";
  if (status === 401 || status === 403) return "這個邀請連結已經失效，請聯絡管理者重新發送邀請連結。";
  return "目前無法完成加入，請稍後再試一次。";
}

function render(): void {
  if (!app) return;
  if (state === "joined") {
    app.innerHTML = `<section class="panel consent-panel" aria-labelledby="consent-heading">
      <p class="eyebrow">家人候診提醒</p><h1 id="consent-heading">已加入</h1>
      <div role="status"><p class="message">已加入，可以關閉這個頁面了。</p><p class="message">如果你也是管理者，不帶邀請連結再次使用 LINE 登入，就會回到管理者畫面。</p></div>
    </section>`;
    return;
  }
  app.innerHTML = `<section class="panel consent-panel" aria-labelledby="consent-heading">
    <p class="eyebrow">家人候診提醒</p><h1 id="consent-heading">確認加入通知</h1>
    <p class="intro">加入後，當家人候診號碼快叫到時，你會收到這個家庭的 LINE 提醒訊息。管理者可以隨時將你從通知名單中移除。</p>
    ${state === "error" ? `<p class="message message-warning" role="alert">${escapeHtml(errorMessage)}</p>` : ""}
    <button class="primary-button" id="confirm-join" type="button" ${state === "submitting" ? "disabled" : ""}>${state === "submitting" ? "處理中…" : "確認加入"}</button>
  </section>`;
  document.querySelector<HTMLButtonElement>("#confirm-join")?.addEventListener("click", submit);
}

async function submit(): Promise<void> {
  if (state === "submitting") return;
  state = "submitting";
  errorMessage = "";
  render();
  try {
    const response = await fetch("/api/recipient/opt-in", {
      method: "POST",
      headers: { accept: "application/json", "x-csrf-token": csrfFromCookie() },
    });
    if (response.status === 204) {
      state = "joined";
    } else {
      state = "error";
      errorMessage = errorTextFor(response.status);
    }
  } catch {
    state = "error";
    errorMessage = "連線失敗，請確認網路後再試一次。";
  } finally {
    render();
  }
}

render();
