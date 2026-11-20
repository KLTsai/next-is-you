# LINE rich menu "current progress" button and the message quota

Research completed 2026-11-20. Scope: whether a family member can tap a rich menu button in the LINE chat and get the current queue progress back as a reply that does not count toward the LINE Official Account's monthly message quota; how the rich menu, webhook, and reply API fit together; current Taiwan plan quotas; and what a separate staging and production setup means for menus. Primary sources only: developers.line.biz documentation and API reference, and LINE Biz-Solutions Taiwan pages on tw.linebiz.com. All pages were read on 2026-11-20. Each claim is labelled **Source** (what the source says) or **Inference** (my reasoning). Nothing was sent to any LINE channel. This is supporting evidence, not implementation authority; adopt anything from it through a GitHub issue first.

Project context used for the inference parts: the product already pushes LINE messages through the Messaging API but has no webhook message handling and no rich menu. [README.md](../README.md) requires "a Login channel and a Messaging channel under the same provider". [docs/CI-CD.md](../docs/CI-CD.md) says staging and production share one LINE Login channel and that `LINE_CHANNEL_ACCESS_TOKEN` is absent in both until Issue #22 authorizes a live pilot.

## Summary of answers

1. **Yes, the reply is free of quota.** LINE lists reply messages as a sending method "not counted as message count"; push, multicast, broadcast, and narrowcast are counted. LINE Taiwan's 2026 price announcement lists "Messaging API 的 Reply API" among the 免付費 message types.
2. **Use a postback action, set through the Messaging API.** A tap on a postback area sends a `postback` webhook event with a reply token and the `data` string. A message action sends text as if the user typed it, which arrives as a `message` event and can also be answered with a reply. Only the Messaging API can put a postback action on a rich menu; LINE Official Account Manager offers coupon, URL, text, stamp card, or nothing.
3. **Reply tokens are single-use and short-lived.** Use them within one minute of receiving the webhook; a used or expired token returns `400 Invalid reply token` and nothing is sent. A late answer cannot fall back to a free reply; only a push (which counts) would reach the user.
4. **Webhook rules.** HTTPS with a publicly trusted certificate, HMAC-SHA256 signature check on the raw body with the channel secret, return `200`, and respond within 2 seconds or the delivery is logged as `request_timeout`. Redelivery is off by default; redelivered events keep the same `webhookEventId` and reply token.
5. **Taiwan plans from 2026-11-01:** 輕用量 NT$0 with 200 free messages, 中用量 NT$1,000 with 3,000, 高用量 NT$1,400 with 6,000 (excl. tax). Only 高用量 can buy more, at NT$0.2 per message up to 50,000 and NT$0.15 after. The fees rose on 2026-11-01; the free message counts did not change.
6. **Menu precedence:** per-user menu (API) over default menu (API) over default menu (Manager). A menu made in Manager can only be edited in Manager, and an API menu only through the API.
7. **Staging and production:** a rich menu, webhook URL, channel secret, and quota all belong to one LINE Official Account and its Messaging API channel. User IDs differ per provider, so a staging Official Account in another provider would also need its own Login channel for recipient IDs to match.

---

## 1. Rich menu actions and what the webhook receives

### 1.1 Postback action

**Source** ([Messaging API reference, Postback action](https://developers.line.biz/en/reference/messaging-api/#postback-action), accessed 2026-11-20): "When a control associated with this action is tapped, a postback event is returned via webhook with the specified string in the `data` property." `data` is required, "Max character limit: 300". `displayText` is optional: "Text displayed on the LINE chat screen as a message sent by the user when the action is performed", also max 300. The older `text` property is "【Deprecated】" and was "Returned from the server through a webhook". `inputOption` can be `closeRichMenu`, `openRichMenu`, `openKeyboard`, or `openVoice`, on LINE 12.6.0 or later.

**Source** ([Messaging API reference, Postback event](https://developers.line.biz/en/reference/messaging-api/#postback-event), accessed 2026-11-20): the event has `type` `postback`, a `replyToken` "used to send reply message to this event", `postback.data`, and the common properties including `source.userId`, `webhookEventId`, and `deliveryContext.isRedelivery`. "You can reply to postback events."

**Source** ([Receive messages (webhook)](https://developers.line.biz/en/docs/messaging-api/receiving-messages/), accessed 2026-11-20): the postback event is received "When a user triggers a postback action. You can reply to this event", in one-on-one chats, group chats, and multi-person chats.

### 1.2 Message action

**Source** ([Messaging API reference, Message action](https://developers.line.biz/en/reference/messaging-api/#message-action), accessed 2026-11-20): "When a control associated with this action is tapped, the string in the `text` property is sent as a message from the user." `text` is required, max 300 characters.

**Source** ([Receive messages (webhook)](https://developers.line.biz/en/docs/messaging-api/receiving-messages/), accessed 2026-11-20): a message event arrives "When a user sends a message. You can reply to this event."

**Inference.** Both actions produce an event with a reply token, so both can get a free reply. Postback is the better fit: the bot gets a fixed machine string instead of free text it must match, the user cannot trigger it by accident by typing, and `displayText` still leaves a visible line in the chat such as 查看目前進度. The reference wording ("displayed on the LINE chat screen") and the deprecation note on `text` suggest `displayText` is not delivered as a separate message event; I did not find a page that says so outright, so confirm it in the first local integration test.

### 1.3 Replying

**Source** ([Messaging API reference, Send reply message](https://developers.line.biz/en/reference/messaging-api/#send-reply-message), accessed 2026-11-20): `POST https://api.line.me/v2/bot/message/reply` with `replyToken` and `messages` (max 5 message objects), plus optional `notificationDisabled`. Rate limit "2,000 requests per second". Error `400` if "An invalid reply token is specified" or "An invalid message object is specified"; "The messages aren't sent if an error is returned."

**Source** ([Display a loading animation](https://developers.line.biz/en/docs/messaging-api/use-loading-indicator/), accessed 2026-11-20): `POST https://api.line.me/v2/bot/chat/loading/start` shows a loading animation in a one-on-one chat for 5 to 60 seconds, or until a new message arrives from the account.

## 2. Does the reply count toward the monthly quota?

### 2.1 LINE Developers

**Source** ([Messaging API pricing](https://developers.line.biz/en/docs/messaging-api/pricing/), accessed 2026-11-20): "Regarding the Messaging API, not all messages sent are counted towards the number of messages for the subscription plan." Counted: push, multicast, broadcast, narrowcast. "Sending methods that are not counted as message count: Reply messages." Counting is per recipient: "The number of messages is counted by the number of people you send a message to." When the monthly limit is exceeded, "an error response will be returned and the messages won't be sent." The page sends Taiwan readers to [tw.linebiz.com LINE Official Account](https://tw.linebiz.com/service/account-solutions/line-official-account/) and the [Taiwan pricing FAQ](https://tw.linebiz.com/faq/oa-price/).

**Source** ([Messaging API reference, Get number of messages sent this month](https://developers.line.biz/en/reference/messaging-api/#get-consumption) and the "Get number of sent reply messages" section of the [same reference](https://developers.line.biz/en/reference/messaging-api/), accessed 2026-11-20): `GET /v2/bot/message/quota/consumption` returns an approximate count that "includes the number of messages sent from LINE Official Account Manager". Reply volume is reported separately by `GET /v2/bot/message/delivery/reply?date={yyyyMMdd}`.

### 2.2 LINE Taiwan plans and the 2026-11-01 change

**Source** ([LINE官方帳號 2026 價格方案調整公告](https://tw.linebiz.com/column/LINEOA-2026-Price-Plan/), published 2026-09-01, accessed 2026-11-20): "新版價格方案預計自 2026 年 11 月 1 日起生效", amounts exclude tax.

| Plan | Monthly fee before | Monthly fee from 2026-11-01 | Free messages per month | Extra messages |
| --- | --- | --- | --- | --- |
| 輕用量 | NT$0 | NT$0 | 200 | Not available |
| 中用量 | NT$800 | NT$1,000 | 3,000 | Not available; upgrade to 高用量 |
| 高用量 | NT$1,200 | NT$1,400 | 6,000 | NT$0.2 each for messages 1 to 50,000; NT$0.15 each from 50,001 |

The same announcement lists as 免付費 messages: 加入好友歡迎訊息, 一對一聊天訊息, 自動回應訊息, AI 自動回應訊息, and "Messaging API 的 Reply API". Existing paid accounts that kept 中用量 or 高用量 after 2026-10-27 accepted the new prices.

**Source** ([tw.linebiz.com LINE Official Account](https://tw.linebiz.com/service/account-solutions/line-official-account/), accessed 2026-11-20): "不計入訊息費用的項目：一對一聊天訊息、自動回應訊息、加入好友的歡迎訊息、Messaging API 中的 Reply API 功能". Counted messages are "群發訊息、分眾訊息、API訊息". Counting uses Japan time: "台灣時間23:00起傳送的訊息會被計算到隔日".

**Source** ([FAQ 訊息費用的計價方式](https://tw.linebiz.com/faq/oa-price/message-price-list/), accessed 2026-11-20): still shows the pre-change fees (NT$800 and NT$1,200) with the note "LINE 官方帳號價格方案將於 2026/11/1 起調整". The announcement above is the newer page.

**Inference.** A reply to a rich menu tap is free under both the developer rules and the Taiwan plan rules. The quota only matters for the existing reminder pushes. On 輕用量 that is 200 recipient-messages per month per Official Account, shared with anything sent from Manager.

## 3. Reply token validity and late answers

**Source** ([Messaging API reference, Reply token](https://developers.line.biz/en/reference/messaging-api/#send-reply-message-reply-token), accessed 2026-11-20):

- "Reply tokens can only be used once."
- "Reply tokens must be used within one minute after receiving the webhook. Use beyond one minute isn't guaranteed to work."
- Tokens in redelivered webhooks can be used within one minute of the redelivery, except when the original token was already used or "20 minutes have passed since the event occurred."
- "The time limit for reply tokens is subject to change without notice ... don't rely on the time limit for implementation. Also, use reply tokens as soon as possible."

**Source** ([Messaging API reference, Error responses](https://developers.line.biz/en/reference/messaging-api/#error-responses), accessed 2026-11-20): "Invalid reply token" covers "Sent a reply message using an expired reply token" and "Sent a reply message using a used reply token."

**Source** ([Messaging API reference, Common properties](https://developers.line.biz/en/reference/messaging-api/#common-properties), accessed 2026-11-20): when the channel `mode` is `standby`, "the webhook event won't contain a reply token".

**Inference.** If the bot answers late, LINE rejects the reply and the user sees nothing (or only their own `displayText`). The only way to still answer is a push message, which counts against the quota. The reply should therefore be built from data the Worker already has, not from a live hospital fetch, and a failed reply should be logged rather than turned into a push.

## 4. Rich menu setup and precedence

### 4.1 Manager versus Messaging API

**Source** ([Rich menus overview](https://developers.line.biz/en/docs/messaging-api/rich-menus-overview/), accessed 2026-11-20):

- Two tools: LINE Official Account Manager (GUI, templates, display period, statistics in Manager) and the Messaging API ("You can set postback action and datetime picker action on a rich menu", tab switching, statistics through the API).
- "Only one tool for one rich menu ... A rich menu created with the LINE Official Account Manager is retrievable and editable only through the LINE Official Account Manager. Likewise, you can't use the LINE Official Account Manager on the rich menu created with the Messaging API."
- Default menus can be set by either tool; per-user menus only by the Messaging API.
- "Rich menus aren't displayed on LINE for PC (macOS, Windows)."
- API setup steps: create the rich menu, upload its image, set it as default.

**Source** ([LINE Biz-Solutions manual, 圖文選單](https://tw.linebiz.com/manual/line-official-account/oa-manager-richmenu/), accessed 2026-11-20): each area's action can be 「優惠券、網址、文字、集點卡、不設定」; "僅能向用戶顯示一個圖文選單，如果期間重複，將無法設定。" Postback is not offered.

**Inference.** A Manager menu cannot send a postback. Its 文字 action behaves like a message action, so a Manager menu could still trigger a free reply through a `message` event, but the bot would have to match free text and the text would also hit any Manager auto-reply keywords. The API is the cleaner path and keeps the menu definition in the repository.

### 4.2 Display priority and timing

**Source** ([Rich menus overview, Display priority](https://developers.line.biz/en/docs/messaging-api/rich-menus-overview/#rich-menu-display), and [reference, Set default rich menu](https://developers.line.biz/en/reference/messaging-api/#set-default-rich-menu), accessed 2026-11-20): highest to lowest: per-user menu set with the Messaging API, default menu set with the Messaging API, default menu set with Manager. Per-user changes take effect immediately; an API default menu change takes effect "When the user re-opens the chat. It may take up to a minute"; a Manager default changes when the user re-opens the chat. Users who are not friends see the default menu.

### 4.3 Per-user menus and limits

**Source** ([reference, Link rich menu to user](https://developers.line.biz/en/reference/messaging-api/#link-rich-menu-to-user), accessed 2026-11-20): `POST /v2/bot/user/{userId}/richmenu/{richMenuId}`. "Only one rich menu can be linked to a user at one time." Linking returns `200` but silently does nothing for users who deleted their account, blocked the account, are not friends, or for "User IDs that don't exist in the channel such as those that were taken from another channel under a different provider."

**Source** ([reference, Create rich menu](https://developers.line.biz/en/reference/messaging-api/#create-rich-menu) and [Rich menu alias](https://developers.line.biz/en/reference/messaging-api/#rich-menu-alias), accessed 2026-11-20): up to 1,000 rich menus and 1,000 rich menu aliases per LINE Official Account through the Messaging API.

**Source** ([Use per-user rich menus](https://developers.line.biz/en/docs/messaging-api/use-per-user-rich-menus/), accessed 2026-11-20): per-user menus take precedence over the default and change "without the user having to re-enter the chat screen".

**Inference.** One API default menu is enough for this feature: the button means the same thing for everyone, and the bot decides what to answer from `source.userId`. Per-user menus are only worth it later, for example to show the button only to recipients with an active visit, and that adds link and unlink calls at visit start and stop.

## 5. Webhook requirements

**Source** ([Build a bot, Set a webhook URL](https://developers.line.biz/en/docs/messaging-api/building-bot/#setting-webhook-url), accessed 2026-11-20): "Only one bot server endpoint can be set in the webhook URL." It "must use HTTPS and have an SSL/TLS certificate issued by a certificate authority widely trusted by general web browsers. Self-signed certificates aren't permitted." Then click **Verify** and enable **Use webhook**.

**Source** ([Build a bot, Greeting messages and auto-reply messages](https://developers.line.biz/en/docs/messaging-api/building-bot/#settings-on-line-official-account-manager), accessed 2026-11-20): greeting and auto-reply messages default to **Enabled** when the channel is created; if the Messaging API handles responses, set them to **Disabled** in Manager. Using both is possible but "you may find it difficult to identify whether an automatic response is sent from a greeting message or response message, or from a bot".

**Source** ([Messaging API reference, Webhooks](https://developers.line.biz/en/reference/messaging-api/#webhooks), accessed 2026-11-20): "The bot server must return status code `200` after it receives the HTTP POST request." LINE may send `"events": []` to confirm communication; answer `200`. Header names are case-insensitive (`x-line-signature`). LINE does not disclose its IP addresses; use signature validation instead. Event processing should be asynchronous.

**Source** ([Verify webhook signature](https://developers.line.biz/en/docs/messaging-api/verify-webhook-signature/), accessed 2026-11-20): compute HMAC-SHA256 over the raw request body with the channel secret as key, base64-encode, compare with `x-line-signature`. "Don't modify the data before verifying the signature" (no deserialization or escaping first). If the signature is missing or does not match, "don't process the webhook event and end the process with an error."

**Source** ([Check webhook error causes and statistics](https://developers.line.biz/en/docs/messaging-api/check-webhook-error-statistics/), accessed 2026-11-20): `request_timeout` means "the bot server didn't return a response within 2 seconds."

**Source** ([Receive messages, Redeliver a webhook](https://developers.line.biz/en/docs/messaging-api/receiving-messages/#webhook-redelivery), accessed 2026-11-20): redelivery is disabled by default and enabled under **Use webhook** then **Webhook redelivery**. It triggers when the server did not return `2xx`; count and interval are not disclosed. "The same webhook event may be sent to your bot server more than once"; use `webhookEventId` to detect duplicates. Redelivered events keep the same event ID and reply token; only `deliveryContext.isRedelivery` changes. LINE "may suspend sending webhooks to your bot server if your bot server fails to receive webhooks for a long time."

**Source** ([Messaging API development guidelines](https://developers.line.biz/en/docs/messaging-api/development-guidelines/), accessed 2026-11-20): new event types and properties may be added without notice; the bot must tolerate them. LINE does not provide logs of webhooks; the developer should keep their own.

**Inference.** On Cloudflare Workers the handler should verify the signature, answer `200` quickly, and do the reply inside the same request or in work that continues after the response. Python Worker cold starts count against the 2-second limit, so measure it in staging. Unknown event types should be acknowledged and ignored.

## 6. Separate staging and production

**Source** ([Messaging API getting started](https://developers.line.biz/en/docs/messaging-api/getting-started/), accessed 2026-11-20): a Messaging API channel is created by enabling the Messaging API on a LINE Official Account in Manager. "Once you assign a provider to manage your LINE Official Account, you can't change or de-assign the provider." Channels cannot be moved between providers later, and "a user is given different user IDs for different providers."

**Source** ([Get user IDs](https://developers.line.biz/en/docs/messaging-api/getting-user-ids/), accessed 2026-11-20): "User IDs are issued different values for each provider, even for the same user. If the provider is the same, the user ID is the same regardless of the channel type (LINE Login channel or Messaging API channel)."

**Source** ([LINE Developers Console overview](https://developers.line.biz/en/docs/line-developers-console/overview/), accessed 2026-11-20): each developer can create up to 10 providers.

**Inference.**

- Each environment needs its own LINE Official Account and Messaging API channel: one webhook URL per channel, so staging and production cannot share one channel without one of them missing webhooks. Each has its own channel secret, access token, quota, and rich menu. The menu-setup script should run per environment with that environment's token.
- Today staging and production share one Login channel. The #129 grilling (2026-11-20) decided that Staging gets its own provider, Official Account, Login channel and Messaging API channel, so each environment's Login and Messaging channels sit in one provider and `source.userId` in its webhooks matches the recipient IDs captured through its own Login. The organizer allowlist and the captain's ID are set per environment.
- Family members would have to add the staging account as a friend to test it, and a link call for a user who is not a friend of that account silently does nothing.
- Staging can stay on 輕用量: replies are free, and its pushes are what use the 200.

## 7. Implications for this product

### 7.1 Design sketch (Inference)

1. **Menu.** One default rich menu per environment, created through the Messaging API by a script kept in the repository, with one area:

   ```json
   {
     "type": "postback",
     "label": "目前進度",
     "data": "v=1&a=progress",
     "displayText": "查看目前進度",
     "inputOption": "closeRichMenu"
   }
   ```

   The `data` carries no visit ID, patient number, or hospital name. It comes from the user's client and is untrusted; who is asking is decided only from `source.userId` in a signed webhook.

2. **Webhook route.** `POST /line/webhook`: read the raw body, verify `x-line-signature` with the Messaging channel secret, reject on mismatch, return `200` for `events: []` and for unknown event types, and drop duplicates by `webhookEventId`.

3. **Answer.** Look up the recipient by `source.userId`, find their running visits, and read the latest stored progress from D1. Do not fetch the hospital page in the request: it risks the 2-second webhook limit and the one-minute reply token, and adds reads to the hospital. Reply once with `POST /v2/bot/message/reply`.

4. **Reply text examples.** Show only the clinic, the patient number, the patient's own status, the estimated people ahead or the highest called number, and when it was read. Never quote the current light as progress: the #136 grilling (2026-11-20) showed it is not the front of the queue. Wording follows the #136 reminders:

   - Checked in, fresh: `眼科 12 診 42 號：已報到，前面約剩 6 人（已叫最大號 38，10:42 更新）。`
   - Not checked in, fresh: `眼科 12 診 42 號：尚未報到，已叫最大號 30，還差 12 號（10:42 更新）。`
   - Running, stale or source unavailable: `眼科 12 診目前無法取得最新進度，最後一次讀取是 10:20。我們會繼續追蹤，輪到前仍會通知您。`
   - Several visits: one line per visit, at most five message objects.
   - No running visit: `目前沒有進行中的叫號追蹤。`
   - Not a known recipient: `這個帳號目前沒有收到任何叫號追蹤的邀請。` (no hint about other people's visits)
   - Sending interrupted: the progress line plus a note that reminders are paused, since a reply is not a reminder.

5. **Failure and recovery.** If the reply fails with `Invalid reply token`, log it and stop. Never fall back to a push, which would cost quota and arrive late. The user can tap again and get a new token.

6. **Privacy.** No patient name, birthday, chart number, or national ID in the menu, postback data, reply text, or logs. Logs keep the event ID, outcome, and a hashed user ID, not the reply body. Only users linked to a visit as recipient or organizer get any progress.

7. **Manager settings per environment.** Turn on **Use webhook**, set greeting and auto-reply messages to **Disabled**, and decide whether to enable webhook redelivery (safe with event ID dedupe; a redelivered tap past one minute just fails to reply).

### 7.2 Open questions

- Does the reply count as a lifecycle event the UI must show (success, pending, failure)? It is read-only, but the organizer may want to know a recipient asked.
- How fresh is stored progress when nobody is close to their turn? If polling slows down between reminders, the reply may need to say when the number was read, as in the examples.
- Should a tap on demand ever trigger a hospital read? That changes the reading load the README rules cover and is outside this note.
- LINE for PC shows no rich menu. Is a typed keyword (a `message` event with the same reply) needed for desktop users?
- Should the button be visible only to recipients with a running visit (per-user menus linked at Start and unlinked at Stop), or to everyone with a generic answer?
- Manager's 回應設定 has a 聊天 / 聊天機器人 mode switch. I did not find a developers.line.biz page that states how chat mode affects webhook delivery; confirm the setting on each account during setup.
- Measure Python Worker cold start plus D1 read plus reply call against the 2-second webhook timeout in staging.
- The `displayText` line likely does not produce a second `message` event; confirm in the first integration test.
