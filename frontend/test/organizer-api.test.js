import test from "node:test";
import assert from "node:assert/strict";
import {
  OrganizerApiError,
  correctVisit,
  createVisit,
  getVisitCorrection,
  listRecipients,
  listVisits,
  startVisit,
  stopVisit,
  updateVisit,
} from "../src/organizer-api.js";

const draftInput = {
  hospital: "ntuh-main",
  date: "2026-09-28",
  department_code: "MED",
  clinic_code: "MED-101",
  session: "afternoon",
  patient_number: 85,
  recipient_ids: ["synthetic-recipient"],
};

function response(payload, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => payload };
}

test("GET clients use the approved organizer list routes and response envelopes", async () => {
  const calls = [];
  const fetcher = async (path, options) => {
    calls.push([path, options]);
    return response(path.endsWith("recipients")
      ? { recipients: [{ id: "r1", display_name: "Family" }] }
      : { visits: [{ id: "v1", state: "draft", source_read: { status: "unavailable", reason: "no_observation" } }] });
  };
  assert.deepEqual(await listRecipients({ fetcher }), { recipients: [{ id: "r1", display_name: "Family" }] });
  assert.deepEqual(await listVisits({ fetcher }), { visits: [{ id: "v1", state: "draft", source_read: { status: "unavailable", reason: "no_observation" } }] });
  assert.deepEqual(calls.map(([path, options]) => [path, options.method, options.headers.accept]), [
    ["/api/organizer/recipients", "GET", "application/json"],
    ["/api/organizer/visits", "GET", "application/json"],
  ]);
});

test("visit projection preserves trusted source links for both supported hospitals", async () => {
  const sourceUrls = [
    "https://registration.ntuh.gov.tw/WebReg/WebReg/ClinicCurrentLightNo?vHospCode=T0",
    "https://reg.skh.org.tw/",
  ];
  const visits = ["ntuh-main", "shin-kong-taipei"].map((hospital, index) => ({
    id: `v${index}`, hospital, source_url: sourceUrls[index],
  }));
  const projection = await listVisits({ fetcher: async () => response({ visits }) });
  assert.deepEqual(projection.visits.map(({ hospital, source_url }) => [hospital, source_url]), [
    ["ntuh-main", sourceUrls[0]],
    ["shin-kong-taipei", sourceUrls[1]],
  ]);
});

test("correction initialization uses a single-visit route with CSRF", async () => {
  let call;
  const result = await getVisitCorrection("draft/one", {
    fetcher: async (path, options) => {
      call = [path, options];
      return response({ patient_number: 85 });
    },
    csrfToken: "csrf-local",
  });
  assert.deepEqual(result, { patient_number: 85 });
  assert.equal(call[0], "/api/organizer/visits/draft%2Fone/correction");
  assert.equal(call[1].method, "GET");
  assert.equal(call[1].headers["x-csrf-token"], "csrf-local");
});

test("draft create, edit, correct, Start, and Stop use approved routes and CSRF", async () => {
  const calls = [];
  const fetcher = async (path, options) => {
    calls.push([path, options]);
    return response(path.endsWith("/start") ? { state: "active" } : path.endsWith("/stop") ? { state: "stopped" } : { id: "v1", state: "draft" }, path === "/api/organizer/visits" ? 201 : 200);
  };
  await createVisit(draftInput, { fetcher, csrfToken: "csrf-local" });
  await updateVisit("v1", draftInput, { fetcher, csrfToken: "csrf-local" });
  await startVisit("v1", { fetcher, csrfToken: "csrf-local" });
  await stopVisit("v1", { fetcher, csrfToken: "csrf-local" });
  await correctVisit("v1", draftInput, { fetcher, csrfToken: "csrf-local" });

  assert.deepEqual(calls.map(([path, options]) => [path, options.method]), [
    ["/api/organizer/visits", "POST"],
    ["/api/organizer/visits/v1", "PATCH"],
    ["/api/organizer/visits/v1/start", "POST"],
    ["/api/organizer/visits/v1/stop", "POST"],
    ["/api/organizer/visits/v1/correct", "POST"],
  ]);
  for (const [, options] of calls) assert.equal(options.headers["x-csrf-token"], "csrf-local");
  assert.deepEqual(JSON.parse(calls[0][1].body), draftInput);
  assert.equal(calls[2][1].body, undefined);
});

test("typed API failures expose only the approved error code", async () => {
  const fetcher = async () => response({ error: { code: "observation_unavailable" } }, 503);
  await assert.rejects(startVisit("v1", { fetcher, csrfToken: "csrf-local" }), (error) => {
    assert.ok(error instanceof OrganizerApiError);
    assert.equal(error.status, 503);
    assert.equal(error.code, "observation_unavailable");
    return true;
  });
});
