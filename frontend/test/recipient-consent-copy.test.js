import assert from "node:assert/strict";
import test from "node:test";
import { joinedMessages } from "../src/recipient-consent-copy.js";

test("the joined state tells an owner who joined as a family member how to return to the manager view", () => {
  const text = joinedMessages().join(" ");
  assert.match(text, /已加入/);
  assert.match(text, /不帶邀請連結/);
  assert.match(text, /再次使用 LINE 登入/);
  assert.match(text, /管理者/);
  assert.doesNotMatch(text, /同時/);
});
