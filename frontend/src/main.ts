import "./style.css";

const status = document.querySelector<HTMLSpanElement>("#service-status");

async function checkLocalWorker(): Promise<void> {
  if (!status) return;
  try {
    const response = await fetch("/api/healthz", { headers: { accept: "application/json" } });
    if (!response.ok) throw new Error(`health check returned ${response.status}`);
    status.textContent = "本機服務正常";
    status.className = "status status-ok";
  } catch {
    status.textContent = "尚未連接本機服務";
    status.className = "status status-pending";
  }
}

void checkLocalWorker();
