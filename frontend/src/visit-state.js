export const VISIT_STATES = Object.freeze(["draft", "active", "stopping", "stopped", "expired"]);
export const SOURCE_STATUSES = Object.freeze(["usable", "unavailable", "stale", "untrusted", "scope_mismatch", "invalid"]);

const STATE_LABELS = Object.freeze({
  draft: "草稿",
  active: "監控中",
  stopping: "停止中",
  stopped: "已停止",
  expired: "已結束",
});
const SOURCE_LABELS = Object.freeze({
  usable: "資料已核對",
  unavailable: "來源暫不可用",
  stale: "資料已過期",
  untrusted: "來源尚未驗證",
  scope_mismatch: "診次資料不相符",
  invalid: "資料格式無效",
});
export function formatVisitState(state) {
  return STATE_LABELS[state] ?? "狀態未知";
}

export function formatSourceStatus(status) {
  return SOURCE_LABELS[status] ?? "來源狀態未知";
}

export function visitStatusKey(visit) {
  if (visit?.state === "draft" && visit.source_read?.status !== "usable") return "source-unavailable";
  if (visit?.state === "expired") return "terminal";
  return visit?.state ?? "terminal";
}

export function canRequestStart(visit) {
  if (!visit || visit.state !== "draft") return false;
  if (!Array.isArray(visit.recipients) || visit.recipients.length === 0) return false;
  if (!visit.hospital || !visit.date || !visit.department_code || !visit.clinic_code || !visit.session) return false;
  // Start performs a new gate-mediated source read. A cached projection may be
  // unavailable or stale; only the server can authorize the state transition.
  return true;
}
