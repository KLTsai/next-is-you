export class OrganizerApiError extends Error {
  constructor(status, code) {
    super(code);
    this.name = "OrganizerApiError";
    this.status = status;
    this.code = code;
  }
}

function csrfFromCookie() {
  if (typeof document === "undefined") return "";
  const item = document.cookie.split(";").map((cookie) => cookie.trim())
    .find((cookie) => cookie.startsWith("__Host-ny_csrf="));
  return item ? decodeURIComponent(item.slice("__Host-ny_csrf=".length)) : "";
}

async function request(path, { method = "GET", body, fetcher = fetch, csrfToken = csrfFromCookie(), csrf = method !== "GET" } = {}) {
  const headers = { accept: "application/json" };
  if (body !== undefined) headers["content-type"] = "application/json";
  if (csrf && csrfToken) headers["x-csrf-token"] = csrfToken;
  const response = await fetcher(path, {
    method,
    headers,
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  let payload = null;
  if (response.status !== 204) {
    try { payload = await response.json(); } catch { payload = null; }
  }
  if (!response.ok) {
    throw new OrganizerApiError(response.status, payload?.error?.code || "request_failed");
  }
  return payload;
}

export function listRecipients(options) {
  return request("/api/organizer/recipients", options);
}

export function listVisits(options) {
  return request("/api/organizer/visits", options);
}

export function getVisitCorrection(id, options = {}) {
  return request(`/api/organizer/visits/${encodeURIComponent(id)}/correction`, { ...options, csrf: true });
}

export function createVisit(input, options = {}) {
  return request("/api/organizer/visits", { ...options, method: "POST", body: input });
}

export function updateVisit(id, input, options = {}) {
  return request(`/api/organizer/visits/${encodeURIComponent(id)}`, { ...options, method: "PATCH", body: input });
}

export function startVisit(id, options = {}) {
  return request(`/api/organizer/visits/${encodeURIComponent(id)}/start`, { ...options, method: "POST" });
}

export function stopVisit(id, options = {}) {
  return request(`/api/organizer/visits/${encodeURIComponent(id)}/stop`, { ...options, method: "POST" });
}

export function correctVisit(id, input, options = {}) {
  return request(`/api/organizer/visits/${encodeURIComponent(id)}/correct`, { ...options, method: "POST", body: input });
}
