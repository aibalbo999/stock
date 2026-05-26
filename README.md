# AI 產業鏈台股分析與自動化報告生成系統

FastAPI + Streamlit + Celery/Redis 的台股主題研究系統。系統會依分析主題由 AI 拆解子題、抓取國內外資料、建立候選公司、驗證證據，再生成一般人可閱讀的 HTML 投資研究報告。

> 本專案是研究與決策輔助工具，不是自動下單系統，也不構成投資建議。

## 目前能力

- AI 主題拆解：由 LLM 依主題產生可執行研究任務，包含子題、研究目的、必查證據、風險焦點、搜尋 query 與台股候選研究清單。
- 查詢可追蹤：AI 產生的每組資料查詢會保留語言、證據類型與驗證假設，方便檢查「為什麼抓這批資料」。
- 查詢自動補強：若 query 太籠統、未對齊研究證據/風險，或缺少有效國際查詢，系統會產生 `query_quality_gap` 補強查詢。
- 拆解自我修復：若第一次拆解缺少必要研究面向，系統會把品質缺口交回 AI 自動修正一次，並只採用分數更高的版本。
- 資料抓取：支援固定 RSS、Google News RSS 動態 query、手動補充新聞與市場資料刷新。
- 公司公開文件：可手動匯入或依股票自動搜尋年報、法說會、公開說明書與重大訊息線索，並寫入 RAG 與個股資料審計；官方/MOPS/交易所/公司 IR 來源會優先於第三方摘要。
- 公司文件補抓會回傳每檔股票的官方搜尋計畫，包含 MOPS、交易所、櫃買中心與 PDF/IR 查詢，方便追蹤「系統實際往哪裡找原始文件」。
- 個股資料審計會區分必要與建議公司文件；目前必要文件為高品質年報，建議文件為高品質法說/投資人簡報。
- 前端補充資料頁可直接匯入公司公開文件，也可貼 URL 自動抓取頁面文字；匯入後會顯示來源分級與品質分數，並同步寫入 RAG 與公司文件審計。
- RAG/檢索：新聞文本進向量庫，報告生成時會取回相關證據。
- 白名單與候選驗證：靜態白名單仍是安全底線；AI 自組候選清單需通過來源驗證後才會升格。
- 弱證據分級：單一文章、單一來源或證據信心低於 75 分只會標成 `weak_evidence`，不會直接進正式分析股票。
- 品質門檻：報告會檢查 AI 拆解任務完整度、候選證據信心、來源篇數、來源家數、時間戳覆蓋、近期資料比例、股價/月營收/財務/估值覆蓋。
- 風險控制：資料不足時報告自動降級為研究草稿，並限制可投入資金上限。
- 個股分析：包含商業模式、護城河、產業趨勢、財務健康、估值、情境分析、12-24 個月展望。
- 前端介面：Streamlit 提供分析、報告、資料、設定頁；報告以 HTML 卡片式閱讀為主。
- 排程與背景任務：Celery + Redis 支援背景產報與定時排程。
- 時區：系統顯示時間以 Asia/Taipei 為準。
- LLM 韌性：Gemini 遇到 429/500/502/503/504 會依 `.env` 重試策略短暫重試，再輪調下一把 key；全部失敗才降級為規則引擎草稿。
- 模型可用性控管：若本輪報告未啟用 LLM 或 LLM 呼叫失敗，品質門檻會標示為需謹慎判讀，並限制投資行動。
- 個股資料足夠性審計：每份報告可逐檔檢查股價、月營收、五年財報、估值、公司文本與 AI 歸因是否足夠，避免整體品質通過但單一公司證據不足。
- 動態白名單證據回寫：AI 驗證出的候選公司會回寫到新聞 entity mapping，讓後續審計、補資料與重跑能查到同一批公司證據。
- 個股缺口自動補強：若個股審計發現股價、月營收、五年財報、估值、公司文本或 AI 歸因不足，Follow-up 會自動規劃補資料並重跑。
- 候選追蹤降噪：正式報告品質與個股資料皆通過時，未升格候選公司改列追蹤更新，並只保留最值得補證據的前 5 檔，不再視為本輪必補資料缺口。

## 核心安全護欄

- 不提交 `.env`、SQLite DB、向量庫、報告輸出、快取與 Celery beat DB。
- API key 使用 `.env` 的 `GOOGLE_API_KEYS` 或 `GOOGLE_API_KEY`，可用逗號設定多組 Gemini key 輪調。
- LLM 不能只憑模型回答把公司放進產業鏈；候選公司需同時命中公司實體與主題證據關鍵詞。
- 子題拆解不可只輸出熱門股票或關鍵字，必須先說明產業因果、要查的資料與要監控的風險。
- 搜尋 query 必須對應研究目的、必查證據或風險焦點；每個子題至少保留國際查詢，避免只看台灣新聞造成落後訊號。
- `AI`、`熱門股` 這類空泛字詞不會被視為有效查詢；即使是英文，也必須能對應具體證據或風險才算有效國際查詢。
- AI 拆解任務若缺少必要研究面向或分數過低，報告會自動降級，不允許直接形成投資行動。
- AI 自我修復只允許補齊研究任務品質；若修復結果更差，系統會保留原本版本並繼續標示缺口。
- 正式分析股票需至少 2 筆證據、來自 2 個來源，且證據信心分數達 75 分；否則維持弱證據或待補資料。
- 證據信心分數會綜合證據篇數、來源家數、來源日期覆蓋與最新證據日期；低信心候選會自動補抓近期、有日期、多來源資料。
- 每項風險與財務/市場推論都應附來源與日期；缺證據時輸出「目前無足夠數據判斷」。
- 個股分析應優先採用公司原始公開文件、財報與月營收，再輔以新聞與產業資料；若缺官方或高品質公司文件，審計會要求補抓。
- 品質門檻不通過時，報告不應被視為買入清單。

## 快速開始

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

啟動 Redis / PostgreSQL：

```bash
docker compose up -d redis postgres
```

預設使用本機 SQLite。若要改用 Docker PostgreSQL，將 `.env` 的 `DATABASE_URL` 改成：

```bash
DATABASE_URL=postgresql+psycopg://stock_ai:stock_ai_password@localhost:5432/stock_ai
```

設定 LLM：

```bash
PRIMARY_LLM_MODEL=gemini-3.5-flash
LOCAL_LLM_MODEL=gemma-4-31b
GOOGLE_API_KEYS=key1,key2,key3,key4,key5
CANDIDATE_CONFIDENCE_HIGH_THRESHOLD=75
CANDIDATE_CONFIDENCE_MEDIUM_THRESHOLD=45
LLM_MAX_RETRIES_PER_KEY=2
LLM_BASE_RETRY_DELAY_SECONDS=0.5
LLM_MAX_RETRY_DELAY_SECONDS=5.0
```

啟動 API：

```bash
.venv/bin/python -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```

啟動 Streamlit：

```bash
.venv/bin/python -m streamlit run streamlit_app.py --server.address 127.0.0.1 --server.port 8501
```

啟動 Celery worker + beat：

```bash
.venv/bin/python -m celery -A app.tasks.celery_app.celery_app worker -B --loglevel=INFO --pool=solo
```

## 常用 API

- `GET /health`
- `GET /services/status`
- `GET /whitelist`
- `GET /news`
- `POST /news/fetch`
- `POST /ingest/manual`
- `POST /company-filings/manual`
- `POST /company-filings/from-url`
- `POST /company-filings/fetch`
- `GET /company-filings`
- `POST /discovery/topic-plan`
- `POST /discovery/ingest`
- `POST /discovery/candidate-whitelist`
- `POST /pipeline/run`
- `POST /pipeline/run_discovered`
- `POST /reports/generate`
- `POST /reports/generate_async`
- `GET /reports`
- `GET /reports/{report_id}`
- `GET /reports/{report_id}/follow-up/plan`：預覽自動補強/追蹤更新任務，含新鮮度略過原因
- `POST /reports/{report_id}/follow-up/run`：依報告品質缺口與監控清單自動補資料，並可重跑報告
- `DELETE /reports/{report_id}`
- `GET /runs`
- `GET /tasks/{task_id}`
- `GET /tasks/{task_id}/run`
- `GET /schedule`
- `PUT /schedule`
- `POST /maintenance/cleanup`

## 自動補強邏輯

報告產生後，系統會把品質門檻、監控清單與重新研究條件轉成可執行任務。任務分成兩類：

- `required`：資料缺口補強，例如缺股價、月營收、五年財務、估值或來源不足。
- `tracking`：追蹤更新，例如資料品質可用，但監控條件要求重新確認股價、月營收或領先訊號。

若報告含有「候選公司審計」，弱證據或待補證據公司會自動轉成 `required` 補強任務。補抓資料源時，系統會依股票代號、公司名、產業位置、分析主題與排除原因建立 Google News 目標查詢，而不是只掃固定 RSS，讓鴻海、雙鴻、台達電、弘塑等未升格候選能被精準補資料後再驗證。

補強完成且選擇重新產生報告時，系統會用分析主題、股票代號、公司名、產業位置與證據關鍵字建立重新驗證查詢，從新聞庫取回相關文件再驗證候選清單；若弱證據公司升格為 `evidence_supported`，會更新正式分析股票、刷新新增股票的股價/月營收/財務/估值資料，再產生新報告。這避免「資料補到了，但正式股票仍停留在舊清單」。前端會顯示本次重新驗證使用的查詢數、文件數、新升格與降回觀察清單。

若正式報告品質門檻與個股資料審計都已通過，未升格候選公司會改成 `tracking` 追蹤，而不是要求本輪全部補完。追蹤清單會優先保留弱證據、證據篇數較多、來源較多、信心較高的前 5 檔，其餘低證據候選留在報告審計表供人工檢查，避免系統把大量零證據公司都排入自動補抓。

追蹤更新會先做新鮮度檢查，避免浪費 API 額度：

- 股價/量能：5 天
- 月營收：75 天
- 估值：14 天
- 五年財務：150 天
- 公司公開文件：365 天

目前自動補強任務名稱包含：

- 補抓資料源
- 補抓公司公開文件
- 刷新股價/量能
- 刷新月營收
- 刷新五年財務
- 刷新估值
- 重跑主題拆解
- 重跑分析報告

若資料仍在新鮮範圍內，`follow-up/plan` 會把任務列在 `freshness.skipped_details`，前端會顯示最新日期與門檻。需要重新抓取時，可在前端勾選強制更新，或呼叫 API 時傳入：

```json
{
  "purpose": "tracking",
  "rerun_report": true,
  "force_refresh": true
}
```

## 測試與檢查

```bash
.venv/bin/python -m pytest
.venv/bin/python -m ruff check app tests streamlit_app.py
.venv/bin/python -m compileall app streamlit_app.py
```

## 目錄

- `app/api/`：FastAPI endpoints
- `app/services/`：報告生成、主題探索、品質門檻、自動補強任務、RAG 與持久化服務
- `app/data_sources/`：新聞與市場資料來源
- `app/tasks/`：Celery app 與背景任務
- `data/`：公開設定、RSS 來源、靜態 AI 產業鏈白名單
- `tests/`：單元與整合測試
- `streamlit_app.py`：使用者操作介面

## 後續擴充

- 加入 Alembic migrations 取代 `create_all`。
- 將更多財務資料來源接入 Fugle/FinMind 付費或授權 API。
- 擴充主題無關的台股公司 universe，讓 AI 能在不同主題下建立候選清單。
- 加入報告版本比較、回測與投資組合追蹤。
