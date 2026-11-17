import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

for (const page of ["index.html", "recipient-consent.html"]) {
  test(`${page} footer says the service is not an official hospital service`, async () => {
    const html = await readFile(new URL(`../${page}`, import.meta.url), "utf8");
    const footer = html.match(/<footer>([\s\S]*?)<\/footer>/)?.[1] ?? "";
    assert.match(footer, /本服務非醫院官方服務/);
    assert.match(footer, /院方網頁與診間現場資訊為準/);
  });
}
