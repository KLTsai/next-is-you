# LINE text layout on phones and animated icons in Messaging API messages

Research completed 2026-11-27. Scope: how much of a LINE text message fits on one line and in a notification preview on common phones, what formatting a text message supports, and whether the Messaging API can carry meaning with an animated icon instead of text, including the quota cost. Pages were read on 2026-11-27. Each claim is labelled **Source** (what a primary source says), **Measured** (something I checked directly against LINE's own servers, with the method), **Secondary** (a non-primary source, used only where no primary source exists), or **Estimate / Inference** (my reasoning). Nothing was sent to any LINE channel; no claim here is a live-provider observation of the LINE app. This is supporting evidence, not implementation authority; adopt anything from it through a GitHub issue first.

**Scope change:** the captain excluded sticker messages from consideration during this research. Question 2b (sticker messages) is not answered, and the quota and notification-preview questions are answered for text messages with LINE emoji and for non-sticker options only.

## Summary of answers

1. **Characters per line: no primary source.** LINE does not publish the text bubble width or the chat font size in points. A Japanese how-to site reports that a received bubble wraps at about 15 full-width characters and at fewer than 15 with the Large font setting. Treat 15 as an unverified estimate.
2. **The LINE font size setting changes it.** Users can choose Small, Medium, Large, or Extra large, and on iOS can follow the device text size. Larger settings mean fewer characters per line.
3. **Notification preview: only partly documented.** Android truncates collapsed notification body text to one line by default. Apple does not publish a line count. LINE's help center only says previews can be turned on or off. For a direct communication notification, iOS shows the sender's name in the title area. With previews hidden, iOS shows only the app icon and the title "Notification".
4. **Formatting: line breaks only.** A `text` message supports plain text, `\n` line breaks, Unicode emoji, and LINE emoji. Nothing in the docs mentions bold or markup. Bold (`weight: bold`) exists only in Flex Message text components.
5. **Link previews: controlled by the viewer.** LINE builds URL previews from `og:title`, `og:description`, and `og:image`, and each user can turn "URL previews" on or off. Whether a URL becomes a link at all depends on the OS. No doc says Messaging API text is excluded from previews.
6. **LINE emoji in text messages are not animated.** Bots can use up to 20 LINE emoji per text message from the 45 product IDs on LINE's list. I checked all 45 against LINE's CDN: none has an animation asset, while two animated emoji sets from the LINE Store both do.
7. **The only non-sticker animated option is a Flex image.** A Flex Message image with `animated: true` plays an APNG. Limits: at most 300 KB, up to 10 per message, and playback depends on the user's "Auto-play GIFs" setting. Image messages accept only JPEG or PNG and have no animated property.
8. **Quota is counted per recipient, not per message object.** Adding emoji, or adding another message object to the same push request, costs nothing extra. A second push request costs another message per recipient.

---

## 1. Readability of a text message

### 1.1 Characters per line in a text bubble

**Source, absence:** The Messaging API reference and docs give the text message limit ("Max character limit: 5000", counted in UTF-16 code units) but say nothing about bubble width, chat font size, or where text wraps ([Messaging API reference, Text message](https://developers.line.biz/en/reference/messaging-api/#text-message); [Character counting in a text](https://developers.line.biz/en/docs/messaging-api/text-character-count/)). I found no LINE help page that does either. Flex bubbles have named widths (`nano`, `micro`, `deca`, `hecto`, `kilo`, `mega`, `giga`, default `mega`), but those are Flex containers, not text bubbles ([Messaging API reference, Bubble](https://developers.line.biz/en/reference/messaging-api/#bubble)).

**Secondary** ([minto.tech, LINE 改行](https://minto.tech/line-kaigyou/), read 2026-11-27): received bubbles wrap at "全角でおおよそ15文字前後" and the sender's own bubbles at about 17. With the Large font setting, wrapping happens at "15文字より少なく". Width also varies with "機種・文字サイズ・絵文字の有無". The article does not name the devices or say how it measured.

**Secondary** ([linestep, LINE公式アカウント 文字数](https://linestep.jp/2022/08/17/line-official-account-word-count/), read 2026-11-27): recommends at most about 13 characters per line for emphasized text, on the reasoning that people take in 9 to 13 characters at a glance. It also says about 300 characters fill one screen without a rich menu, measured on an iPhone 12 mini (5.4 inch).

**Estimate:** at the default (Medium) font size, a received LINE text bubble holds roughly 14 to 16 full-width CJK characters per line on phones 360 to 412 dp wide (iPhone 390 pt wide included). This range comes from the secondary figure of about 15, widened by one character either way because those screens differ by about 15% in width. It is not a LINE-published number. I did not measure it on a device.

### 1.2 Font size setting

**Source** ([LINE Help Center, Customizing chats](https://help.line.me/line/smartphone/?contentId=20005811), read 2026-11-27): on mobile, "Select **Small**, **Medium**, **Large**, or **Extra large**". On iOS "you can apply the font size set on your smartphone to the LINE app" by turning on "Use device settings".

**Source** ([Flex Message layout, Scaling to size according to the font size setting](https://developers.line.biz/en/docs/messaging-api/flex-message-layout/#size-scaling)): Flex text scales with this setting only when `scaling: true` is set (LINE 13.6.0 or later). The docs say nothing about plain text messages here.

**Inference:** a plain text bubble follows the user's chat font size, as the secondary source says. A line that fits at Medium can wrap at Large or Extra large, and that cannot be prevented. The way to cope is to make each line make sense even if it wraps, not to rely on an exact width.

### 1.3 Notification preview

**Source, Android** ([Create a notification](https://developer.android.com/develop/ui/views/notifications/build-notification)): "By default, the notification's text content is truncated to fit one line. You can show additional information by creating an expandable notification." A collapsed notification "displays an icon, a title, and a small amount of text content". On the lock screen, `VISIBILITY_PRIVATE` shows "only basic information, such as the notification's icon and the content title". The user "always has ultimate control" over lock-screen visibility.

**Source, iOS** ([Apple HIG, Notifications](https://developer.apple.com/design/human-interface-guidelines/notifications)): "In a notification related to direct communication, the system automatically displays the sender's name in the title area." Also: "don't truncate your message - the system does this automatically when necessary." And: "In Settings, people can choose to hide notification previews for all apps. In this situation, the system shows only your app icon and the default title Notification." Apple does not publish how many body lines a banner or lock-screen notification shows.

**Source, LINE** ([LINE Help Center, Convenient notification settings](https://help.line.me/line/smartphone/?contentId=20011381), read 2026-11-27): users can "set whether to show LINE message previews on your device's screen when you receive a notification" with a "Message previews" toggle. On iOS 15 or later, "The profile icons of users that send you messages will appear in pop-up notifications". The page does not say what a preview contains or how long it can be.

**Source, LINE** ([Messaging API reference, Flex Message](https://developers.line.biz/en/reference/messaging-api/#flex-message)): for non-text messages, the `altText` "will appear in the device's notifications, talk list, and quote messages". For text messages, the preview is the text itself.

**Inference:** the preview title is most likely the LINE Official Account's display name, with the message text as the body. This follows from the iOS sender-name rule and from LINE showing profile icons in notifications, but LINE does not document it. The body can be cut to one line on Android when collapsed, and to an undocumented length on iOS. Users who turned off LINE message previews or OS previews see no content at all.

**Estimate:** an Android collapsed notification line holds roughly 15 to 20 full-width characters. This assumes the default 14 sp body text, CJK glyphs one em wide, and about 90 dp lost to the icon and margins on a 360 to 412 dp screen. I did not measure it. The practical rule is to put the key fact in the first 15 characters of the message.

### 1.4 Formatting in a text message

**Source** ([Messaging API reference, Text message](https://developers.line.biz/en/reference/messaging-api/#text-message)): the `text` property may include LINE emoji (via `$` placeholders and the `emojis` property) and Unicode emoji. Max 5000 characters. The object has no style properties. `\n` counts as one character ([LINE Developers FAQ, character count](https://developers.line.biz/en/faq/)).

**Source** ([Messaging API reference, Flex Message text](https://developers.line.biz/en/reference/messaging-api/#f-text)): bold exists only in Flex text: "`weight` ... `regular` or `bold`". Flex text also has `wrap`, `maxLines`, and `scaling`.

**Inference:** plain text messages can only use line breaks, spacing, and emoji for structure. Bold or controlled layout requires a Flex Message, which needs an `altText` for notifications.

### 1.5 Bare URLs and link preview cards

**Source** ([LINE Developers FAQ, "How are URL previews generated in chats?"](https://developers.line.biz/en/faq/), tagged LINE app, LINE Official Account, Messaging API): "LINE uses Open Graph Protocol tags from websites to generate URL previews": `og:title`, `og:description`, `og:image`. If they are missing, LINE falls back to the `<title>`, the description tag, or body text.

**Source** (same FAQ, "Why do URLs in text messages sometimes not become links?"): "The behavior of converting a URL in a text message to a link depends on the specifications of the OS ... this isn't controlled by the LINE app." It also says "adding a space or a line break before the URL in the text message may be recognized as a valid URL."

**Source** ([LINE Help Center, Customizing chats](https://help.line.me/line/smartphone/?contentId=20005811)): users can "Turn on/off **URL previews**". "In order to generate URL previews, links shared in chats are also sent to LINE's servers."

**Inference:** a bare URL in a bot text message can show a preview card if the viewer has URL previews on, because the FAQ answer is tagged for the Messaging API. The bot cannot force a preview on or off, and the card's content comes from the target page's OGP tags. I did not test this against a live channel.

---

## 2. Can the Messaging API show meaning with an animated icon?

### 2a. LINE emoji in text messages

**Source** ([Messaging API reference, Text message](https://developers.line.biz/en/reference/messaging-api/#text-message)): `emojis` is an array of LINE emoji objects with "Max: 20 LINE emoji". Each object has an `index` (the position of the `$` in `text`; a wrong position returns `400 Bad request`), a `productId`, and an `emojiId`. Text message (v2) does the same with `{key}` substitution, "Up to 20 emoji" ([Text message (v2)](https://developers.line.biz/en/reference/messaging-api/#text-message-v2)).

**Source** ([LINE emoji](https://developers.line.biz/en/docs/messaging-api/emoji-list/)): bots can send only the emoji listed on that page. It lists 45 product IDs, from `670e0cce840a8236ddd4ee4c` and `5ac1bfd5040ab15980c9b435` through `5ac21184040ab15980c9b43a`. The page does not say whether any of them are animated. "LINE original unicode emojis" were discontinued on 2022-03-31.

**Source** ([Character counting in a text](https://developers.line.biz/en/docs/messaging-api/text-character-count/)): for the 5000-character limit, each `$` placeholder is counted as the emoji's alternative text, which is "the text displayed instead of the emoji on devices that can't display LINE emojis". Also: "LINE doesn't disclose the alternative text for LINE emojis." The FAQ gives "(love)" as an example.

**Measured** (2026-11-27, HTTP checks against LINE's public sticker CDN; the CDN is not documented, so this is evidence, not a contract):
- Animated LINE emoji on the CDN have a `/sticonshop/v1/sticon/{productId}/iPhone/{emojiId}_animation.png` file next to the static `{emojiId}.png`. I confirmed this on two emoji sets that the LINE Store marks with its animation icon (`67c6c461e8e6283159209e31`, `61276856db3e5947326668ef`): both returned `200` for `001_animation.png`.
- For all 45 bot-sendable product IDs, `001.png` returns `200` and `001_animation.png` returns `404`.
- Each bot-sendable set's `meta.json` contains only `productId`, `altTexts`, and `orders`, with no animation flag. The alt texts are short English labels such as "moon heart eyes".

**Inference:** none of the emoji a bot may send are animated, so a LINE emoji in a text message renders as a static image. Where the emoji cannot be shown, and probably in notification previews, it appears as undisclosed alternative text (often English). An emoji cannot reliably carry a Traditional Chinese meaning by itself.

### 2b. Sticker messages

Excluded by the captain. Not researched further.

### 2c. Other animated options (non-sticker)

**Source** ([Messaging API reference, Flex image](https://developers.line.biz/en/reference/messaging-api/#f-image)): "When this is `true`, an animated image (APNG) plays. You can specify a value of `true` up to 10 images in a single message ... Animated images larger than 300 KB aren't played back." The image must be JPEG or PNG, at most 1024 x 1024 px, and at most "300 KB when the `animated` property is `true`". If it does not play, check: "Is `Auto-play GIFs` enabled in the LINE app settings?" The animation repeats `num_plays` times from the APNG `acTL` chunk, and 0 means forever.

**Source** ([Messaging API reference, Flex Message](https://developers.line.biz/en/reference/messaging-api/#flex-message)): a Flex Message needs an `altText` (max 1500 characters, Unicode emoji allowed), which "will appear in the device's notifications, talk list, and quote messages".

**Source** ([Messaging API reference, Image message](https://developers.line.biz/en/reference/messaging-api/#image-message)): image messages accept only "JPEG or PNG" and have no `animated` property. The reference does not say whether an APNG sent as an image message animates.

**Source** ([Messaging API reference, Imagemap message](https://developers.line.biz/en/reference/messaging-api/#imagemap-message)): an imagemap can "play a video on the image and display a label with a hyperlink after the video is finished" (mp4, max 200 MB). It also has an `altText` for notifications. The reference warns the video "may not play properly on the user's device", and it is a video, not an icon.

**Source** ([Messaging API reference, Display a loading animation](https://developers.line.biz/en/reference/messaging-api/#display-a-loading-indicator)): the loading animation is shown only while the user has the chat open. It disappears after 5 to 60 seconds or when a message arrives, and it carries no meaning. It cannot be used for a notice.

**Inference:** the only non-sticker way to show an animated icon is a Flex Message with an animated APNG image. Even then, the notification and chat list show the `altText` and not the animation. The animation can be stopped by the user's Auto-play GIFs setting or by a file over 300 KB.

### 2d. Quota when sending several message objects (text and LINE emoji only)

**Source** ([Messaging API pricing, How to count the number of messages sent](https://developers.line.biz/en/docs/messaging-api/pricing/#how-to-count-the-number-of-messages-sent)), quoted: "The number of messages is counted by the number of people you send a message to. Suppose you send a push message with four message objects in a single request to a chatroom with five people. Here, the number of messages sent is five. The number of message objects in a request doesn't affect the number of messages sent."

**Source** (same page): push, multicast, broadcast, and narrowcast messages count toward the quota; reply messages do not. Messages to users who blocked the account, or who cannot receive them, are not counted.

**Source** ([Messaging API reference, Send push message](https://developers.line.biz/en/reference/messaging-api/#send-push-message)): `messages` takes "Max: 5" message objects per request.

**Inference:** LINE emoji inside a text message cost nothing extra. A text message plus a Flex animated image in the same push request costs 1 message per recipient. Sending them as two push requests costs 2.

### 2e. What a notification shows for an icon

**Source:** for Flex and imagemap messages, the notification shows the `altText` set by the sender ([Flex Message](https://developers.line.biz/en/reference/messaging-api/#flex-message), [Imagemap message](https://developers.line.biz/en/reference/messaging-api/#imagemap-message)). For a LINE emoji in a text message, LINE only says the alternative text exists and is not disclosed ([Character counting in a text](https://developers.line.biz/en/docs/messaging-api/text-character-count/)). No primary source describes how a notification preview renders a LINE emoji.

**Inference:** an icon alone does not appear as an icon in the notification. A Flex image shows whatever `altText` we write. An emoji-only text message would show LINE's undisclosed alternative text or a rendered glyph, and we control neither.

---

## Implications for organizer notices (#152) and the family unavailable message

- **Max characters per line:** write each line at most **13 full-width characters**, with explicit `\n` breaks. This sits below the estimated 14 to 16 that fit at the default font size, so a line should not wrap at Medium on 360 to 412 dp phones. It also matches the 13-character glance guideline from the secondary source. At Large or Extra large the font setting can still wrap a line, so each line should read correctly when wrapped. Put the key fact, for example 「設定者已收到通知」 (8 characters), in the first line: Android may show only one collapsed line of the notification, and iOS truncates at an undocumented point. These numbers are estimates and should be confirmed with live screenshots on a 390 pt iPhone and a 360 dp Android phone at Medium and Large before they become acceptance criteria.
- **Can an animated icon alone replace 「設定者已收到通知」? No.**
  - Bot-sendable LINE emoji are static (measured: none of the 45 sets has an animation asset). In notifications they would show undisclosed, often English, alternative text.
  - A Flex animated APNG is the only non-sticker animated option, and it needs an `altText`, which is what the notification and chat list show. The text therefore has to be written in `altText` anyway. The animation is limited to 300 KB, can be turned off by the user's Auto-play GIFs setting, and needs an HTTPS-hosted asset.
- **Cost and limits if an icon is added next to the text:** no extra quota if it goes in the same push request as the text (quota is counted per recipient per request, at most 5 message objects). One extra message per recipient if it goes in a separate request. At most 20 LINE emoji per text message, and at most 10 animated images per Flex Message.
- **Recommendation:** keep 「設定者已收到通知」 as plain text in the message (and in `altText` if a Flex Message is ever used). Any icon should only decorate the text, never replace it.
