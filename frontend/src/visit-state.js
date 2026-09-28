export const VISIT_STATUSES = Object.freeze([
  "draft",
  "active",
  "stopping",
  "stopped",
  "source-unavailable",
  "terminal",
]);

const LABELS = Object.freeze({
  draft: "草稿",
  active: "監控中",
  stopping: "停止中",
  stopped: "已停止",
  "source-unavailable": "來源 unavailable",
  terminal: "已結束",
});

export function formatStatus(status) {
  return LABELS[status] ?? "狀態未知";
}

export function isFreshMatchingObservation(observation, expected, now = Date.now()) {
  if (!observation || observation.trustworthy !== true) return false;
  if (!Number.isInteger(observation.currentNumber) || observation.currentNumber <= 0) return false;
  if (!expected || !expected.departmentCode || !expected.clinicCode || !expected.session) return false;
  if (["hospital", "visitDate", "departmentCode", "clinicCode", "session"].some((key) => observation[key] !== expected[key])) return false;
  const observedAt = Date.parse(observation.observedAt);
  return Number.isFinite(observedAt) && observedAt <= now && now - observedAt <= 120_000;
}

export function canStartVisit(visit, now = Date.now()) {
  return visit?.status === "draft" && visit.recipients?.length > 0 && isFreshMatchingObservation(visit.observation, visit, now);
}
