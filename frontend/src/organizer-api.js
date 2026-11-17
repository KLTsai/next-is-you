export class OrganizerApiError extends Error {
  constructor(status, code, visitDate) {
    super(code);
    this.name = "OrganizerApiError";
    this.status = status;
    this.code = code;
    // Set only for the refusal that tells the organizer which day Start opens.
    if (visitDate) this.visitDate = visitDate;
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
    throw new OrganizerApiError(response.status, payload?.error?.code || "request_failed", payload?.error?.visit_date);
  }
  return payload;
}

export function listRecipients(options) {
  return request("/api/organizer/recipients", options);
}

export function listVisits(options) {
  return request("/api/organizer/visits", options);
}

export function listHospitals(options) {
  return request("/api/organizer/hospitals", options);
}

export function listClinics(hospital, department, date, options = {}) {
  const query = new URLSearchParams({ department, date }).toString();
  return request(`/api/organizer/hospitals/${encodeURIComponent(hospital)}/clinics?${query}`, options);
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

export function removeVisitRecipient(visitId, recipientId, options = {}) {
  return request(`/api/visits/${encodeURIComponent(visitId)}/recipients/${encodeURIComponent(recipientId)}`, {
    ...options,
    method: "DELETE",
  });
}

export function correctVisit(id, input, options = {}) {
  return request(`/api/organizer/visits/${encodeURIComponent(id)}/correct`, { ...options, method: "POST", body: input });
}

export function createInvitation(memberLabel, options = {}) {
  return request("/api/organizer/invitations", { ...options, method: "POST", body: { member_label: memberLabel } });
}

export function withdrawMember(recipientId, options = {}) {
  return request(`/api/organizer/recipients/${encodeURIComponent(recipientId)}/withdraw`, { ...options, method: "POST" });
}
