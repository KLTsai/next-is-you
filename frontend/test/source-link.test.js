import test from "node:test";
import assert from "node:assert/strict";
import { safeSourceUrl, sourceLinkMarkup } from "../src/source-link.js";

test("official API links render as safe external links for both hospitals", () => {
  const links = [
    "https://registration.ntuh.gov.tw/WebReg/WebReg/ClinicCurrentLightNo?vHospCode=T0",
    "https://reg.skh.org.tw/",
  ];
  for (const link of links) {
    assert.equal(safeSourceUrl(link), link);
    const markup = sourceLinkMarkup(link);
    assert.ok(markup.includes(`href="${link}"`));
    assert.match(markup, /target="_blank" rel="noreferrer"/);
  }
});

test("absent or unsafe API links are never rendered as clickable links", () => {
  for (const link of [undefined, "", "javascript:alert(1)", "http://hospital.example", "https://user:pass@hospital.example"]) {
    assert.equal(safeSourceUrl(link), null);
    assert.equal(sourceLinkMarkup(link), "來源連結尚未提供");
  }
});
