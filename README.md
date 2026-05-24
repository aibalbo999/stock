# AI 產業鏈台股分析與自動化報告生成系統

FastAPI + Streamlit + Celery/Redis 的台股主題研究系統。系統會依分析主題由 AI 拆解子題、抓取國內外資料、建立候選公司、驗證證據，再生成一般人可閱讀的 HTML 投資研究報告。

> 本專案是研究與決策輔助工具，不是自動下單系統，也不構成投資建議。

## 目前能力

- AI 主題拆解：由 LLM 依主題產生可執行研究任務，包含子題、研究目的、必查證據、風險焦點、搜尋 query 與台股候選研究清單。
- 資料抓取：支援固定 RSS、Google News RSS 動態 query、手動補充新聞與市場資料刷新。
- RAG/檢索：新聞文本進向量庫，報告生成時會取回相關證據。
- 白名單與候選驗證：靜態白名單仍是安全底線；AI 自組候選清單需通過來源驗證後才會升格。
- 弱證據分級：單一文章或單一來源只會標成 `weak_evidence`，不會直接進正式分析股票。
- 品質門檻：報告會檢查來源篇數、來源家數、時間戳覆蓋、近期資料比例、股價/月營收/財務/估值覆蓋。
- 風險控制：資料不足時報告自動降級為研究草稿，並限制可投入資金上限。
- 個股分析：包含商業模式、護城河、產業趨勢、財務健康、估值、情境分析、12-24 個月展望。
- 前端介面：Streamlit 提供分析、報告、資料、設定頁；報告以 HTML 卡片式閱讀為主。
- 排程與背景任務：Celery + Redis 支援背景產報與定時排程。
- 時區：系統顯示時間以 Asia/Taipei 為準。

## 核心安全護欄

- 不提交 `.env`、SQLite DB、向量庫、報告輸出、快取與 Celery beat DB。
- API key 使用 `.env` 的 `GOOGLE_API_KEYS` 或 `GOOGLE_API_KEY`，可用逗號設定多組 Gemini key 輪調。
- LLM 不能只憑模型回答把公司放進產業鏈；候選公司需同時命中公司實體與主題證據關鍵詞。
- 子題拆解不可只輸出熱門股票或關鍵字，必須先說明產業因果、要查的資料與要監控的風險。
- 正式分析股票需至少 2 筆證據且來自 2 個來源；否則維持弱證據或待補資料。
- 每項風險與財務/市場推論都應附來源與日期；缺證據時輸出「目前無足夠數據判斷」。
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
- `POST /discovery/topic-plan`
- `POST /discovery/ingest`
- `POST /discovery/candidate-whitelist`
- `POST /pipeline/run`
- `POST /pipeline/run_discovered`
- `POST /reports/generate`
- `POST /reports/generate_async`
- `GET /reports`
- `GET /reports/{report_id}`
- `DELETE /reports/{report_id}`
- `GET /runs`
- `GET /tasks/{task_id}`
- `GET /tasks/{task_id}/run`
- `GET /schedule`
- `PUT /schedule`
- `POST /maintenance/cleanup`

## 測試與檢查

```bash
.venv/bin/python -m pytest
.venv/bin/python -m ruff check app tests streamlit_app.py
.venv/bin/python -m compileall app streamlit_app.py
```

## 目錄

- `app/api/`：FastAPI endpoints
- `app/services/`：報告生成、主題探索、品質門檻、RAG 與持久化服務
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
