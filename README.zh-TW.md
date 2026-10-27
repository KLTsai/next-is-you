# Next is you

> 盯著醫院看診進度頁，在號碼快到時發一則 LINE 提醒給你。

[English](README.md) · [繁體中文 (當前)]

## 這是什麼

台大醫院眼科的下午診常常一跑就是好幾個小時。家中一位成員在候診區守著進度，其他人則待在別處，希望能剛好趕到。看診號碼燈牌有自己的節奏，想真正知道何時該出門，誠實的辦法只有一條：自己手動一直重新整理進度頁。

Next is you 就是替你做這件事的小工具。擁有者在瀏覽器開啟固定網址，把當天的門診資訊建成草稿（醫院、科別、診間、醫師、下午診），按下 Start。接著一個 Cloudflare Worker 會依排程讀取公開的看診進度頁，比對該門診的那一列，當目前叫號接近時，發一則 LINE 訊息給擁有者所邀請的收件人。

這是給一個家庭與他們所邀請的人使用的工具，不是公開服務。在擁有者本人透過 Issue #22 的手機實測明確授權真實發送之前，所有環境下的提醒都處於保留狀態。

## 現況

以下是今日誠實的現況。權威來源是 GitHub 上的 issue tracker。

| 項目 | 狀態 | Issue |
| --- | --- | --- |
| 私人 HTTPS 服務已部署、提醒保留中 | 已就位；僅為保留態的 bootstrap，不會真實發送 | [#18](https://github.com/KLTsai/next-is-you/issues/18) |
| LINE 邀請與退出 UI | 進行中 | [#19](https://github.com/KLTsai/next-is-you/issues/19) |
| 台大眼科下午診 reader | 具備 fixture 與本地整合證據；真實醫院行為尚未驗證 | [#17](https://github.com/KLTsai/next-is-you/issues/17)、[#20](https://github.com/KLTsai/next-is-you/issues/20) |
| 私人儲存復原與營運就緒 | 待辦 | [#21](https://github.com/KLTsai/next-is-you/issues/21) |
| 擁有者本人手機實測（首次真實提醒） | 尚未進行 | [#22](https://github.com/KLTsai/next-is-you/issues/22) |

以上任何一項都不代表已經有一則真實的病患提醒被送出。此現況表是本文件中唯一描述「今日可用」與「仍在建置」差異的地方；任何仍受未結 issue 把關的功能，不會在本文件其他段落被誇張宣稱。

**未來方向：** 目前的單一醫院範圍（台大總院區眼科下午診）是未來支援多家醫院的起點；每新增一個來源，都要先累積一份與 [Issue #17](https://github.com/KLTsai/next-is-you/issues/17) 同樣形式的、證明該公開頁可用的證據。目前的前端照現況提供使用，未來規劃以 React、Vue、Svelte 等主流 web framework 重新設計；尚未選定框架。

## 運作方式

```
   擁有者的瀏覽器             Cloudflare Worker                     LINE
   --------------             -----------------                    ----
   建立草稿  ─────────►   把 reminder 存入 D1
     （醫院、診間、                 │
      醫師、時段）                   ▼
                              每分鐘 cron tick
                                   │
                                   ▼
                              NTUH reader 擷取公開的
                              看診進度列表，比對該門診的
                              那一列
                                   │
                                   ▼
                              send-gate（保留中） ──────►  當叫號接近時
                                                           發一則訊息
```

Reader 只會保留它實際比對到的欄位（診間、醫師、clinic type、目前叫號）給擁有者草稿指定的那一間門診，不會留存原始 response body。Send-gate 是依環境獨立的保留開關：在 Issue #22 實測明確翻轉它之前，任何環境都不會真的發出 LINE 訊息，這是刻意的設計。

## 擁有者的日常使用

日常使用只需要瀏覽器。擁有者的穩定來源網址是一個固定的 `workers.dev` URL，於首次部署時建立；請使用當時存下的書籤。

1. 用任何瀏覽器開啟那個穩定網址。
2. 為當天的門診建立草稿。
3. 按下 **Start**。
4. 關掉瀏覽器。服務會依每分鐘排程繼續盯著進度頁。

目前提醒仍處於保留狀態，按下 Start **不會**觸發真實提醒；這仍待[Issue #22 手機實測](https://github.com/KLTsai/next-is-you/issues/22)。上方流程描述的是實測授權真實提醒後的預期行為。

停止或保留：

- **停止某則提醒**：在 UI 中打開目前的 reminder，確認 **停止提醒**。已在送出途中的通知可能會先完成，才確認停止。詳見 [HTTPS 服務文件的停止與復原段落](docs/HTTPS-SERVICE.md#stop-failure-recovery-and-rollback)。
- **保留整個服務**（當系統出現異常時）：擁有者登入後，透過已授權的狀態 API 設定 recovery hold。對應的 console 片段在 [HTTPS 服務的手動驗收段落](docs/HTTPS-SERVICE.md#manual-deployed-acceptance-unrun)；recovery hold 會跨 Worker 重啟保留，且必須在任何還原或程式碼 rollback 之前先設定。
- **部署 rollback**：使用 [stop, failure recovery and rollback 段落](docs/HTTPS-SERVICE.md#stop-failure-recovery-and-rollback)中原生的 Wrangler rollback 程序。只能 rollback 到與目前 schema 及已保留的 SQLite class 相容的版本；本 README 刻意不重述完整命令。

首次部署（secrets、Login channel 註冊、resource 準備）屬於另一個擁有者設定流程，詳見 [docs/HTTPS-SERVICE.md](docs/HTTPS-SERVICE.md)。

## 想自架的其他家庭

自架是條真實可走的路，但有真實的前置條件，也有真實的範圍限制。

前置條件：

- 一個 Cloudflare 帳號，可用 Workers、D1 與 SQLite Durable Objects（保留態 bootstrap 以 Free 方案為目標；相關配額詳見 [HTTPS 服務文件中的 Free 方案配額表](docs/HTTPS-SERVICE.md#free-plan-and-origin-decision)）。
- 一個 LINE Developers 帳號，於同一個 provider 底下擁有一個 Login channel 與一個 Messaging channel；擁有者的 LINE subject（一個穩定識別碼，不是顯示名稱）必須私下提供。
- 你自己 fork 的這個 repository。

範圍限制：目前這個專案唯一讀取的醫院來源是台大醫院總院區眼科下午診（13:30-16:30），並比對官方公開看診進度頁上 Dr. appointment 列表的那一列。確切支援範圍與已知落差見 [docs/NTUH-READER.md](docs/NTUH-READER.md)。任何其他醫院、科別或時段，都需要以 [Issue #17](https://github.com/KLTsai/next-is-you/issues/17) 的形式先做自己的證據蒐集，才能加入。

完整的擁有者設定流程（本地驗證、Wrangler login、建立 D1、apply migrations、部署、LINE callback 註冊、驗收），請依序照 [docs/HTTPS-SERVICE.md](docs/HTTPS-SERVICE.md) 執行。

## 開發者

一次安裝 locked 相依：

```sh
npm ci
uv sync --group dev --locked
```

本地入口：

- **完整本地服務 rehearsal：** 執行 `npm run dev:rehearsal`，開啟 <http://127.0.0.1:8787>。使用真實的本地 D1 與 SQLite Durable Object bindings、synthetic login、fake providers，不需要憑證。首次的 synthetic setup、建立草稿、Start/Stop、fake 發送、重複 tick 與重啟歷程，請依 [complete rehearsal guide](docs/LOCAL-REHEARSAL.md) 走過一遍。
- **輕量 shell smoke：** 執行 `npm run dev:local`，開啟 <http://127.0.0.1:8787>。只建置 UI 並在 loopback 上跑 Python ASGI app，沒有 Cloudflare bindings。使用空白範本時，`curl -i http://127.0.0.1:8787/auth/line` 回 `503`。不會驗證資料庫功能或提醒發送。

與 CI 等價的 deterministic 檢查：

```sh
uv run playwright install chromium
uv run ruff format --check src tests
uv run ruff check src tests
npm run typecheck
npm run test:ui
npm run build
uv run python scripts/check_migrations.py
uv run pytest -q
git diff --check
```

這些是 fixture/mock 與本地自動化證據；不會連到真實醫院或 LINE、不會部署、也不證明手機端送達。CI 實際跑的 gate 見 [CI workflow](.github/workflows/ci.yml)。

相關文件：

- [完整 rehearsal 指南](docs/LOCAL-REHEARSAL.md)
- [NTUH reader 指南](docs/NTUH-READER.md)
- [Pre-live checklist](docs/PRE-LIVE-CHECKLIST.md)
- [本地手動 checklist](docs/NIY-020-LOCAL-MANUAL-CHECKLIST.md)
- [HTTPS 服務準備](docs/HTTPS-SERVICE.md)
- [Research 索引](research/README.md)，包含 [NIY-021 findings summary](research/NIY-021-findings-summary.md)
- [Issue-tracker 慣例](docs/agents/issue-tracker.md)；歷史紀錄見[封存目錄](docs/archive/tickets/README.md)

目前的工作追蹤在 [GitHub Issues](https://github.com/KLTsai/next-is-you/issues)。

## 範圍與非目標

Next is you 是一個私人家庭工具。它不會：

- 變成公開 SaaS 或支援多租戶 onboarding。
- 計算 ETA、預測下一號、或從鄰列推論叫號。
- 加入付費方案功能、依賴外部服務的 status badge、或行銷頁面。

在擁有者本人的手機實測（[Issue #22](https://github.com/KLTsai/next-is-you/issues/22)）明確授權真實提醒之前，所有環境下的提醒發送都處於保留狀態。

## 隱私

Next is you 的設計是盡量少留東西：

- **會儲存什麼：** 邀請紀錄、同意紀錄，以及用於排程與去重複的 outbox events。不會留存任何原始醫院 response body；reader 只保留比對到的欄位（診間、醫師、clinic type、目前叫號）給擁有者草稿指定的那一間門診。
- **當天截止：** 看診日當天台北時間 23:59 之後，active reminders 會過期，不再送出任何通知。
- **active-data 清理：** drafts 與過期的 reminders 會在台北 23:59 截止後 48 小時內清掉；停止的 reminders 會在 Stop 後 48 小時內清掉。
- **退出：** 收件人退出時，其紀錄即被刪除。
- **備份：** 備份保留期與 active-data 清理分開管理；相關部署儲存與備份 gate 詳見 [pre-live checklist](docs/PRE-LIVE-CHECKLIST.md)。

確切機制存在於儲存與生命週期文件中；本段只用平白話描述它們。擁有者的穩定來源是一個公開的 `workers.dev` URL，其靜態 shell 與 `/api/healthz` endpoint 對任何人都可觸及；organizer 資料與寫入操作則需要在 allowlist 中的 LINE session 與 CSRF。
