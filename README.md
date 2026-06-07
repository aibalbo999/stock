# AI 產業鏈台股分析與自動化報告生成系統

FastAPI + Streamlit + Celery/Redis 的台股主題研究系統。系統會依分析主題由 AI 拆解子題、抓取國內外資料、建立候選公司、驗證證據，再生成一般人可閱讀的 HTML 投資研究報告。

> 本專案是研究與決策輔助工具，不是自動下單系統，也不構成投資建議。

## 目前能力

- AI 主題拆解：由 LLM 依主題產生可執行研究任務，包含子題、研究目的、必查證據、風險焦點、搜尋 query 與台股候選研究清單。
- 查詢可追蹤：AI 產生的每組資料查詢會保留語言、證據類型與驗證假設，方便檢查「為什麼抓這批資料」。
- 來源意圖可追蹤：AI 子題會保留/自動補齊 `source_intents`，用來標示應補新聞、公司公開文件、財務、估值、產能、政策或國際資料。
- 查詢自動補強：若 query 太籠統、未對齊研究證據/風險，或缺少有效國際查詢，系統會產生 `query_quality_gap` 補強查詢。
- 拆解自我修復：若第一次拆解缺少必要研究面向，系統會把品質缺口交回 AI 自動修正一次，並只採用分數更高的版本。
- 資料抓取：支援固定 RSS、Google News RSS 動態 query、手動補充新聞與市場資料刷新；固定來源已分成台灣新聞、AI 晶片供應商、雲端資本支出、AI 需求、資料中心電力/基礎建設、半導體產業等類別。
- 來源覆蓋審計：固定來源與動態來源會統計來源類別入庫量，避免深度分析只堆新聞而漏掉雲端 capex、資料中心電力、半導體設備與國際供應鏈訊號。
- 子題覆蓋審計：每個 AI 拆出的研究子題會計算相關文件數、來源家數、來源類別與缺少的文字資料意圖；若有子題完全沒有相關來源，系統會自動追加補抓。
- 來源選擇可解釋：固定來源會記錄命中的主題詞、匹配分數、啟用/跳過原因與來源意圖；缺資料時補抓 query 會優先瞄準缺失子題。
- 自動補強閉環：來源審計若發現缺子題或弱子題，會自動轉成補抓資料、重跑主題拆解與重跑分析任務；品質門檻會阻擋缺來源子題的報告進入可行動狀態。
- 分析強度可調：AI 探索式流程支援快速、標準、深度；標準預設會保留多輪補抓，深度最多補抓 5 輪，若連續補不到有效新來源會提前停止。
- 自動升級策略：快速/標準模式若遇到拆題不足、缺多個子題來源或候選證據嚴重偏低，會自動提高補強輪數與查詢批次，並在 audit 記錄停止原因。
- 公司公開文件：可手動匯入或依股票自動搜尋年報、法說會、公開說明書與重大訊息線索，並寫入 RAG 與個股資料審計；官方/MOPS/交易所/公司 IR 來源會優先於第三方摘要。
- 公司文件補抓會回傳每檔股票的官方搜尋計畫，包含 MOPS、交易所、櫃買中心與 PDF/IR 查詢，方便追蹤「系統實際往哪裡找原始文件」。
- 公司文件抓取支援設定化 User-Agent、Proxy、403/429/5xx 重試、重試時 User-Agent/proxy 身份輪換，以及可選的瀏覽器渲染後援，降低公開文件入口被擋或動態頁面空殼被誤判為公司缺資料的機率；PDF 解析可設定 `auto`、`pdfplumber`、`unstructured` 或 `pypdf`，PDF 與 HTML/IR 網頁都會盡量把財報表格轉成可檢索文字。
- 個股資料審計會區分必要與建議公司文件；目前必要文件為高品質年報，建議文件為高品質法說/投資人簡報。
- 前端補充資料頁可直接匯入公司公開文件，也可貼 URL 自動抓取 HTML 或 PDF 文字；匯入後會顯示來源分級與品質分數，並同步寫入 RAG 與公司文件審計。URL 匯入會阻擋 localhost、內網 IP 與非 HTTP(S) 位址，降低 SSRF 風險。
- URL 匯入還會檢查抓回內容的長度、公司識別與文件類型線索，避免把登入頁、空白頁或一般新聞誤存成公司原始文件。
- RAG/檢索：新聞文本進向量庫，報告生成時會取回相關證據；Chroma 可明確指定 multilingual embedding 模型，向量化時會把標題、來源、公司對應與內文一起送入 embedding，BM25 關鍵字檢索也會納入 entity metadata（股票代號、公司名稱、標題、來源與內文），再與向量檢索做 hybrid search；混合排序會套用來源可信度權重，讓官方/交易所/主流財經來源優先於論壇或投資網誌，降低股票代號、公司名稱、CoWoS 等專有名詞漏抓與公司歸屬錯置風險。每次檢索會保留 retrieval trace，拆出 vector score、BM25 raw/normalized score、來源權重、final score 與 reranker status，方便追查某篇來源為何被送進報告。
- RAG 來源歸屬：新聞入庫時會把資料庫既有的公司 entity mapping 一併保留到 `NewsDocument` 與 Chroma metadata；向量庫取回後仍能知道來源實際對應哪幾檔股票。報告取證會把本輪目標股票傳入向量檢索，先排除 metadata 已明確對應其他股票的來源，再進入 rerank 與報告排序，降低動態候選或同名公司在後續報告生成時被重新誤判。
- GraphRAG 輔助脈絡：白名單與 AI 升格候選會被轉成輕量產業鏈關係圖譜，提供上下游檢索 context；`GET /supply-chain/graph?tickers=3324&topic=AI伺服器散熱` 會回傳同一份圖譜導出的 `retrieval_plan`，包含公司鄰居、同業基本面與上下游關係確認查詢。`GET /supply-chain/graph/reasoning?tickers=3324&target_ticker=2382` 會計算 taxonomy graph shortest path，輸出 LLM 可用的上下游衝擊 context、方向標籤、evidence policy 與 Neo4j shortest-path Cypher template。`GET /supply-chain/graph/cypher-plan?tickers=3324&target_ticker=2382&question=上下游衝擊&use_llm=true` 會讓 LLM 產生 Cypher plan，但只在通過 read-only、Company label、白名單關係、參數化與路徑深度驗證後採用，否則退回 deterministic template。報告生成會使用 retrieval plan 擴展 RAG 查詢；路徑推理結果仍只代表產業分工假設，正式投資理由必須有新聞、公司文件、月營收或財報證據支撐。`GET /supply-chain/graph/neo4j` 會輸出 Neo4j Cypher 匯入語句與參數，方便把公司、產業段與上下游/同業關係載入圖資料庫。
- 市場資料快取：五年財報與估值資料會先查 Redis；五年財報預設快取 31 天，估值預設快取 1 天。Redis 暫時不可用時會自動退回 FinMind 抓取，不阻斷分析流程。
- 白名單與候選驗證：靜態白名單仍是安全底線；AI 自組候選清單需通過來源驗證後才會升格。
- 候選升格也會尊重 RAG/資料庫保留的 entity metadata：來源若明確對應其他股票，不得用來支持本候選；來源若已由前段流程標定為本候選，可用 metadata 補足公司實體歸屬，再檢查題材上下文。
- 來源可信分層：候選驗證會把官方/交易所、主流財經新聞、市場資料、產業研究、投資網誌/自媒體與社群來源分層計權；投資網誌、自媒體、社群或論壇來源只能作為背景雜訊參考，不得進入正式證據池、候選信心分、代表來源、風險/機會歸因 `findings_json` 或配置理由。
- 弱證據分級：單一文章、單一來源或證據信心低於 75 分只會標成 `weak_evidence`，不會直接進正式分析股票。
- 品質門檻：報告會檢查 AI 拆解任務完整度、候選證據信心、來源篇數、來源家數、來源時間戳覆蓋、回看區間內來源比例、高可信來源比例、低可信來源比例、RAG embedding / reranker 實際運行狀態，以及股價/月營收/財務/估值覆蓋。
- 報告可信度檢查：報告會先列出可追溯來源、來源多樣性、來源日期新鮮度、公司層級證據、市場/財務覆蓋與風險/機會歸因，並逐檔標示高/中/低可信度與主要限制。
- LLM 補充分析來源歸屬：送入模型的證據摘要會標示來源日期、發布者、標題與公司對應；模型回傳的 claim 會再比對 source_id、claim 中公司與該來源實際對應公司，避免把 A 公司新聞寫成 B 公司結論。
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
- Workflow orchestration：長流程會把拆題、資料抓取、候選重驗證、市場資料、報告建置與自動補強等階段寫入 analysis run payload，保留步驟狀態、摘要、耗時、錯誤與 `resume_from_step` 恢復提示。`WORKFLOW_ENGINE` 預設為 `local`；若設定為 `prefect` 且依賴可用，pipeline endpoint 會以 Prefect flow 包裝執行；若設定為 `temporal` 且 Temporal SDK / 連線設定完整，pipeline endpoint 會 start configured workflow 並回傳 workflow/run id；若設定為 `airflow` 且 `AIRFLOW_API_URL` / `AIRFLOW_DAG_ID` 完整，pipeline endpoint 會透過 Airflow REST API 建立 DAG run 並回傳外部 run id。
- 架構分層：候選重驗證、探索式 pipeline 的候選公司文件重驗證決策與補文件缺口摘要、公司公開文件升降級與 API 匯入/列表 use case、同步報告產生與 run lifecycle use case、報告查詢/候選審計/刪除 use case、新聞/市場/排程/維護資料工具 use case、手動新聞 RAG 匯入 use case、GraphRAG 圖譜查詢 use case、topic discovery API use case、run/task 查詢與非同步報告排隊 use case、補強後保留/排除邏輯、探索式資料抓取/source audit/補抓查詢 workflow、市場資料刷新/快取補缺、一般報告建置、標準報告 pipeline 執行、AI 主題探索 pipeline 執行、報告補強 follow-up 上下文載入/判斷/計畫/執行、workflow checkpoint，以及探索式報告產生、品質門檻與 run payload 組裝已抽離到 service 層；API service wiring 集中在 `app/api/service_factory.py`，FastAPI app 組裝移到 `app/api/app_factory.py`，舊測試/腳本 helper 的匯出名單隔離在 `app/api/compatibility_exports.py`，實際相容邊界在 `app/services/api_compatibility.py`，`app/api/main.py` 只保留 thin app entry 與相容 delegator，`app/api/legacy_facade.py` 只保留 deprecated import alias。系統狀態、GraphRAG/供應鏈圖譜、公司公開文件、AI/LLM discovery、pipeline/workflow、資料操作與 run/task、報告與 follow-up endpoint 已拆到 router 模組，controller 只保留薄封裝與 endpoint 編排。

## 核心安全護欄

- 不提交 `.env`、SQLite DB、向量庫、報告輸出、快取與 Celery beat DB。
- 提交前可執行 `.venv/bin/python scripts/security_scan.py` 掃描已追蹤檔案中的 Gemini/OpenAI key 與私鑰；預設 `--engine auto` 會優先使用 `detect-secrets`，其次可接 `gitleaks`，兩者都不可用時才退回本地 regex 後援。開發環境可用 `pip install -e ".[dev]"` 安裝 `detect-secrets`，CI 若已有 gitleaks 也可執行 `.venv/bin/python scripts/security_scan.py --engine gitleaks`。
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
python -m pip install --upgrade pip setuptools
pip install -e ".[dev]"
cp .env.example .env
```

macOS 一鍵啟動：

```bash
./start_system.command
```

也可以在 Finder 直接雙擊 `start_system.command`。它會啟動 API 與 Streamlit，避免重複開相同 port，並在視窗中顯示本機與同網路手機可用網址。
需要停止背景服務時，雙擊 `stop_system.command`。

啟動 Redis / PostgreSQL / Neo4j / Browserless / Chroma：

```bash
docker compose up -d redis postgres neo4j browserless chroma
```

若公開資訊觀測站或公司 IR 入口遇到 Cloudflare / CAPTCHA / 空殼頁，可額外啟動 FlareSolverr unlocker profile：

```bash
docker compose --profile unlocker up -d flaresolverr
COMPANY_FILING_BROWSER_RENDER_PROVIDER=flaresolverr
COMPANY_FILING_BROWSER_RENDER_URL=http://127.0.0.1:8191/v1
```

專案預設設定已對齊 Docker PostgreSQL 與 Alembic migration。若在主機端連 Docker PostgreSQL，將 `.env` 的 host 改成 `localhost`；若在 compose 服務內執行，使用 `postgres`：

```bash
# Host-only local process:
DATABASE_URL=postgresql+psycopg://stock_ai:stock_ai_password@localhost:5432/stock_ai
DATABASE_INIT_MODE=alembic

# Docker Compose service:
DATABASE_URL=postgresql+psycopg://stock_ai:stock_ai_password@postgres:5432/stock_ai
DATABASE_INIT_MODE=alembic
```

資料庫 schema 變更請使用 Alembic：

```bash
.venv/bin/alembic upgrade head
.venv/bin/alembic revision --autogenerate -m "describe change"
```

`DATABASE_INIT_MODE` 可設為 `create_all`、`alembic` 或 `none`。正式部署預設為 `alembic`，FastAPI 與 Celery 啟動時會執行 `alembic upgrade head`；若資料庫由外部部署流程管理，可設為 `none`。若要保留 SQLite 快速開發，可在 `.env` 明確設定 `DATABASE_URL=sqlite:///./stock_ai.db` 與 `DATABASE_INIT_MODE=create_all`。既有本機 SQLite 若原本由 `create_all` 建出且 schema 已存在，請先用 `.venv/bin/python -m alembic stamp head` 標記目前版本，再改用 Alembic 管理後續變更。可用 `GET /db/status` 或 `GET /services/status` 檢查 `database.init_mode`、`migration.current_revision`、`migration.head_revision` 與 `migration.up_to_date`，避免資料表存在但 schema 版本落後。`GET /services/status` 也會輸出 `upgrade_capability_matrix`，把 multilingual embedding、LLM SDK、hybrid search、reranker、GraphRAG、API 分層、workflow、Alembic、Redis cache 與公司文件抓取強化逐項標為 `ready`、`degraded` 或 `not_configured`。
若 `DATABASE_URL` 指向 PostgreSQL/MySQL 等非 SQLite 資料庫，系統會拒絕用 `create_all` 啟動，避免正式環境跳過 Alembic 欄位遷移；只有受控的一次性 bootstrap 才應暫時設定 `DATABASE_ALLOW_CREATE_ALL_NON_SQLITE=true`。
初始 migration 以顯式 `op.create_table` / `op.create_index` 固定 schema 快照，測試會執行 `alembic upgrade head` 並用 autogenerate diff 確認 migration 結果與目前 SQLAlchemy metadata 對齊。

設定 LLM：

```bash
LLM_PROVIDER=google_genai
PRIMARY_LLM_MODEL=gemini-3.5-flash
LOCAL_LLM_MODEL=gemini-2.5-flash-lite
LLM_FALLBACK_MODELS=gemini-2.5-flash,gemini-3.1-flash-lite,gemini-2.5-flash-lite,gemma-4-31b-it
GOOGLE_API_KEYS=key1,key2,key3,key4,key5
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
CANDIDATE_CONFIDENCE_HIGH_THRESHOLD=75
CANDIDATE_CONFIDENCE_MEDIUM_THRESHOLD=45
LLM_MAX_RETRIES_PER_KEY=1
LLM_MODEL_QUOTA_COOLDOWN_SECONDS=3600
LLM_QUOTA_HARD_ROUTING_ENABLED=true
LLM_QUOTA_WINDOW_TIMEZONE=America/Los_Angeles
LLM_MODEL_DAILY_REQUEST_BUDGETS=gemini-3.5-flash=250,gemini-2.5-flash=250,gemini-3.1-flash-lite=250,gemini-2.5-flash-lite=250,gemma-4-31b-it=14400
LLM_MODEL_DAILY_TOKEN_BUDGETS=
LLM_BASE_RETRY_DELAY_SECONDS=0.5
LLM_MAX_RETRY_DELAY_SECONDS=5.0
```

免費版 API key 目前採取智慧優先策略：`gemini-3.5-flash` 作為正式報告、GraphRAG 推理、結構化補充分析、LLM reranker 與 Visual RAG PDF 圖片解析的主模型；只有該模型回傳 429/quota、上游錯誤或空回覆時，才依序降級到 `gemini-2.5-flash`、`gemini-3.1-flash-lite`、`gemini-2.5-flash-lite`，最後才使用高額度保底的 `gemma-4-31b-it`。`gemini-embedding-2` 作為 RAG embedding。Google 的 Gemini API rate limits 以 project 計算，不是以 API key 計算，因此 `GOOGLE_API_KEYS` 多把 key 只用於輪替錯誤/分散瞬時失敗，不代表免費 RPD/TPM 會倍增。`gemini-3.5-flash` 保留為第一順位；`gemini-3.5-flash`、`gemini-2.5-flash`、`gemini-3.1-flash-lite` 與 `gemini-2.5-flash-lite` 在本專案以同級免費 request budget 追蹤，`gemma-4-31b-it` 則作為高量文字任務保底。若本機 smoke test 回傳 quota 429，通常代表該 project 今日或當前視窗額度已耗盡。系統會在模型回傳 429 時套用 `LLM_MODEL_QUOTA_COOLDOWN_SECONDS`，短時間跳過該模型，避免每次報告都先撞已耗盡的模型；cooldown 結束後會自動再次把高階模型放回優先嘗試。`GET /llm/quota` 與系統設定頁會顯示 Pacific-day 額度視窗、今日已用 request/token、每模型剩餘估算與目前建議模型；實際限制仍以 Google AI Studio 顯示的 project limit 為準。Imagen / Live 模型偏圖片生成或即時語音互動，不進入目前報告與資料管線核心流程。

`LLM_PROVIDER=google_genai` 會使用官方 `google-genai` SDK 呼叫 Gemini，SDK 不可用或失敗時仍會退回既有 Gemini HTTP key 輪調，最後才使用規則引擎草稿。若需要跨供應商或嚴格模型鏈降級，可改回 `LLM_PROVIDER=litellm`，此時 LiteLLM 會依 `LLM_FALLBACK_MODELS` 逐一降級；Gemini / Gemma 會使用 `GOOGLE_API_KEYS` / `GOOGLE_API_KEY`，`gpt-*` / `openai/*` 會使用 `OPENAI_API_KEY`，`claude*` / `anthropic/*` 會使用 `ANTHROPIC_API_KEY`，只有 `ollama/`、`lm_studio/`、`local/` 前綴的模型會被視為不需 API key 的本地/閘道模型。LiteLLM 執行時若某個候選模型缺少對應 API key，會記錄 `missing_api_key` 並跳到下一個模型，不會把缺 key 呼叫包裝成一般 provider failure。`LOCAL_LLM_MODEL` 也會自動併入 LiteLLM 候選模型；這個欄位目前保留相容既有設定，模型是否需要 key 仍由模型名稱判斷。`GET /llm/status` 會列出 provider、SDK dependency、fallback models、每個 fallback model 的 key readiness 與各供應商 key 是否設定；`GET /services/status` 的 `upgrade_capability_matrix.ai_rag.llm_sdk_and_fallback` 會把 SDK 可用性與 fallback model key readiness 分開列出，只有至少一個 fallback model 有可用 key，或模型明確為 local/ollama/lm_studio 本地閘道時才標為 ready，避免把「有 SDK」誤認成「已有跨模型降級」。`GET /llm/health` 會回傳 `attempt_summary`，包含嘗試次數、用過的 provider/model、HTTP 狀態、主要失敗類型、可重試失敗數、是否曾重試、是否成功前先失敗，以及是否切換 provider/model 備援；報告品質門檻也會揭露模型是否經由重試或備援模型才完成，方便分辨 rate limit、缺 key、SDK dependency 或上游故障。

設定 RAG embedding 與混合檢索：

```bash
USE_CHROMA=true
RAG_EMBEDDING_PROVIDER=google_genai
RAG_EMBEDDING_MODEL=gemini-embedding-2
# RAG_EMBEDDING_OUTPUT_DIMENSIONALITY=768
RAG_INDEX_SCHEMA_VERSION=identity-v2
RAG_ALLOW_CHROMA_DEFAULT_EMBEDDING_FALLBACK=false
RAG_HYBRID_SEARCH_ENABLED=true
RAG_VECTOR_WEIGHT=0.60
RAG_KEYWORD_WEIGHT=0.40
RAG_RERANK_TOP_K=40
RAG_CHROMA_QUERY_TIMEOUT_SECONDS=12
RAG_CHROMA_GET_TIMEOUT_SECONDS=8
RAG_CHROMA_UPSERT_TIMEOUT_SECONDS=30
RAG_RERANKER_PROVIDER=auto
RAG_RERANKER_MODEL=BAAI/bge-reranker-v2-m3
RAG_RERANKER_TEXT_LIMIT=4000
RAG_RERANKER_TIMEOUT_SECONDS=15
RAG_LLM_RERANKER_ENABLED=true
RAG_LLM_RERANKER_MAX_DOCUMENTS=8
COHERE_API_KEY=
```

若使用 `sentence_transformers` provider，請安裝 RAG 額外依賴：

```bash
pip install -e ".[dev,rag]"
```

沒有安裝 embedding provider 或沒有對應 API key 時，系統預設會停用 Chroma 持久化向量庫，改走記憶體 hybrid keyword fallback，避免繁中檢索品質安靜退回 Chroma 預設模型卻被誤認為已啟用 multilingual embedding。只有明確設定 `RAG_ALLOW_CHROMA_DEFAULT_EMBEDDING_FALLBACK=true` 時，才會允許退回 Chroma 預設 embedding。
`RAG_EMBEDDING_PROVIDER` 可設為 `sentence_transformers`、`openai`、`google_genai`、`google` 或 `chroma_default`；OpenAI 需設定 `OPENAI_API_KEY`，Google 需設定 `GOOGLE_API_KEY` 或 `GOOGLE_API_KEYS`。`google_genai` 會用官方 `google-genai` SDK 的 `embed_content`，建議使用已實測可回傳 3072 維向量的 `gemini-embedding-2`；若要維持舊索引相容也可暫用 `gemini-embedding-001`。修改 embedding 模型後請調整或保留 `RAG_INDEX_SCHEMA_VERSION`，讓 Chroma 使用新的 collection，避免不同向量空間混用。`google` 保留 Chroma 既有 `GoogleGenerativeAiEmbeddingFunction` 相容路徑。`GET /services/status` 會回傳 `vector_store.embedding_status.custom_embedding_enabled` 與 `fallback_reason`，用來確認是否真的啟用自訂 embedding，而不是安靜退回 Chroma 預設模型。
若設定 `CHROMA_API_URL=http://localhost:8000` 或 compose 內的 `http://chroma:8000`，`VectorStore` 會改用 Chroma HTTP server；未設定時才使用本地 `VECTOR_DB_PATH` persistent client。`GET /services/status` 會顯示 `vector_store.storage_mode` 與 `chroma_api_url_configured`。
Chroma collection 名稱會納入實際 embedding provider、model 與 `RAG_INDEX_SCHEMA_VERSION`；從 Chroma 預設 embedding 切到繁中/多語 embedding，或修改向量化文本格式（例如新增公司對應 identity header）時，會自動使用不同 collection，避免新舊向量索引混用。若未來調整 embedding 文本欄位或 chunk metadata 規格，請同步調高 `RAG_INDEX_SCHEMA_VERSION`，`GET /services/status` 的 `vector_store.retrieval_status.collection_name_example` 可確認目前會寫入哪個 collection。
`RAG_RERANKER_PROVIDER=auto` 會先嘗試本機 cross-encoder reranker（`bge` / `sentence_transformers`，預設模型 `BAAI/bge-reranker-v2-m3`），若不可用再嘗試 Cohere Rerank；兩者都不可用時，會用既有 LLM SDK/key 對前 `RAG_LLM_RERANKER_MAX_DOCUMENTS` 筆候選做 JSON 排序；LLM reranker 也不可用才退回 hybrid 分數的關鍵字排序 fallback。若要固定本機模型，可設為 `sentence_transformers`、`cross_encoder` 或 `bge`；若要固定 Cohere，可設為 `cohere` 或 `cohere_rerank`，搭配 `RAG_RERANKER_MODEL=rerank-v3.5` 與 `COHERE_API_KEY`；若要固定 LLM reranker，可設為 `llm` 或 `llm_rerank`。`keyword` 仍可作為明確的 lexical fallback，但不會被視為模型級 reranker。Chroma query/get/upsert、模型載入與外部 rerank 都有 timeout；逾時、SDK 缺少、API key 缺少、LLM 回傳不可解析 JSON 或推論失敗時會保留可用排序並退回 keyword，不阻斷報告生成。`GET /services/status` 會回傳 `vector_store.retrieval_status`（hybrid/BM25、中文 n-gram tokenizer、entity metadata 是否納入 embedding/BM25、source credibility weights、keyword corpus limit、權重、rerank top-k 與 timeout 秒數）以及 `vector_store.reranker_status.execution_mode`、`configured_provider`、`resolved_provider`、`auto_candidates`、`quality_tier`、`keyword_fallback`、`model_reranker_ready`、`dependency_available`、`api_key_configured`、`model_available` 與 `fallback_reason`。`upgrade_capability_matrix.ai_rag.reranking` 只有在 cross-encoder、Cohere 或 LLM 這類 learned/API/model reranker 可用時才會標為 `ready`；auto 退回 keyword 時會顯示 `degraded`，避免把 lexical fallback 誤認成模型重排序。

LLM/RAG observability 預設啟用本地 trace（`LLM_OBSERVABILITY_ENABLED=true`、`LLM_OBSERVABILITY_PROVIDER=local`）：每次 LLM result 會附上 provider/model、latency、attempt count、input/output/total token estimate 與成本估算模式；RAG retrieval trace 也會記錄 `duration_ms` 與 reranker status。若要估算 API 成本，可設定 `LLM_INPUT_COST_PER_1K_TOKENS_USD` 與 `LLM_OUTPUT_COST_PER_1K_TOKENS_USD` 作為部署自己的 rate card。外部觀測平台可用 `LLM_OBSERVABILITY_PROVIDER=langsmith` 搭配 `LANGSMITH_API_KEY`，或 `LLM_OBSERVABILITY_PROVIDER=phoenix` 搭配 `PHOENIX_ENDPOINT`；目前 status 會揭露外部 sink 是否已配置，報告執行摘要則保留本地 trace，便於後續接 LangSmith/Phoenix SDK。`GET /services/status` 會回傳 `llm_observability` 與 `upgrade_capability_matrix.ai_rag.llm_observability`，用來確認 token、latency、retrieval latency、reranker status 與成本追蹤欄位是否可用。

設定 GraphRAG / Neo4j：

```bash
NEO4J_URI=neo4j://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=stock_ai_neo4j_password
NEO4J_DATABASE=neo4j
NEO4J_TIMEOUT_SECONDS=15.0
NEO4J_STATUS_CHECK_CONNECTION=true
```

本機可用 `docker compose up -d neo4j` 啟動 Neo4j，或用 `start_system.command` / `.venv/bin/python scripts/start_system.py --start-dependencies` 一次啟動 Redis、Postgres、Neo4j 與 Browserless。一鍵啟動會在本次程序中自動套用 docker-compose 的 Neo4j 預設環境變數（不改寫 `.env`），讓 API/Streamlit 能直接使用本機 GraphRAG 匯入設定。`GET /supply-chain/graph` 會輸出 retrieval hints 與 `retrieval_plan`；`retrieval_plan.evidence_policy` 會明確標示圖譜擴展查詢只作檢索，不得直接當成供應商證據。`GET /supply-chain/graph/reasoning` 會輸出 shortest-path reasoning context 與 Cypher template，可用於分析上下游衝擊、同業傳導或指定兩家公司之間的最短路徑。`GET /supply-chain/graph/cypher-plan` 會建立 guarded LLM Cypher plan：`use_llm=true` 時會把題目、來源股票、目標股票與可用公司清單交給 LLM 產生 JSON Cypher，系統只接受 `MATCH/RETURN/ORDER BY/LIMIT`、`Company` label、`STRUCTURAL_UPSTREAM_TO` / `SAME_SEGMENT_PEER` 關係、白名單股票參數與受控深度；任何寫入語法、未知 schema、非 JSON 或不可信參數都會被拒絕並退回 deterministic plan。`GET /supply-chain/graph/cypher-query` 會先產生同一份 guarded plan，再於 Neo4j 已設定時執行 read-only 查詢；未設定 Neo4j 時會回傳 validated plan 與 `not_configured`，不把外部部署選項誤判為核心 GraphRAG 失敗。`GET /supply-chain/graph/neo4j` 會輸出可匯入 Neo4j 的 Cypher statements 與參數；若已設定 `NEO4J_URI` 並安裝 `neo4j` driver，可用 `POST /supply-chain/graph/neo4j/import` 將目前 GraphRAG 節點與 taxonomy edges 寫入 Neo4j。也可不啟動 API，直接用 `.venv/bin/python -m scripts.import_supply_chain_graph_neo4j --dry-run --tickers 2330 --output graph_payload.json` 檢查匯入 payload；拿掉 `--dry-run` 後會依 `.env` 設定連線匯入 Neo4j。`GET /services/status` 會顯示 GraphRAG retrieval query strategy / evidence policy、shortest-path reasoning strategy / endpoint、agentic Cypher planner strategy / guardrails、live query endpoint、`supply_chain_graph.neo4j_import.payload_export_ready`、payload 格式/節點/關係/statement 數、`ready`、driver 是否可用、目標 database、是否執行連線探測、連線錯誤、fallback reason 與本機 docker 預設啟動提示；因此「可產生 Neo4j 匯入 payload」和「外部 Neo4j 連線已就緒」會分開呈現。能力矩陣也分成 `ai_rag.graphrag_context`、`ai_rag.graphrag_path_reasoning`、`ai_rag.graphrag_agentic_cypher`、`ai_rag.graphrag_live_cypher_query`、`ai_rag.neo4j_payload_export` 與 `ai_rag.neo4j_import`：前三者驗證本機 graph context、shortest-path reasoning 與 guarded LLM Cypher plan 是否可用；`graphrag_live_cypher_query` 只有 Neo4j 連線可用時才會 ready；`neo4j_payload_export` 只要可產生 parameterized Cypher payload 就會是 `ready`；`neo4j_import` 只有外部 Neo4j URI、driver、帳密與連線探測都可用時才會是 `ready`。未設定 URI 時 `neo4j_import` 會標為 `degraded` 並保留 payload 匯出資訊；設定了 URI 但 Neo4j 沒啟動時會顯示 `connection_failed:neo4j`，不會把尚未連上的外部匯入能力標成 ready。這些邊仍只作為檢索與推理脈絡，不得當成直接供應商證據。
若 Docker registry 下載 Neo4j image 卡住，也可用 Homebrew 路徑：`brew install neo4j`、`neo4j-admin dbms set-initial-password stock_ai_neo4j_password`、`brew services start neo4j`。啟動後可用 `.venv/bin/python scripts/upgrade_audit.py --strict-external --local-neo4j-defaults --wait-local-neo4j 20 --local-browser-render-defaults` 驗證 live Neo4j import 與本機 Playwright 文件渲染後援是否同時就緒。
指定股票的 RAG 檢索會套用 target ticker / 公司名稱 / alias 過濾：若文件 metadata 已標成其他公司會被排除；若是舊資料沒有 metadata，必須在標題或內文命中目標代號/名稱/alias 才能進入該股票的檢索候選。報告端重新排序也會再次用 entity mapper 排除「被辨識為別家公司」的文件，降低南亞/南亞科、台達電/光寶科這類張冠李戴風險。

設定市場資料快取：

```bash
MARKET_DATA_CACHE_ENABLED=true
PRICE_HISTORY_CACHE_TTL_SECONDS=86400
MONTHLY_REVENUE_CACHE_TTL_SECONDS=604800
FINANCIAL_METRICS_CACHE_TTL_SECONDS=2678400
VALUATION_METRICS_CACHE_TTL_SECONDS=86400
MARKET_PRICE_PROVIDER_ORDER=finmind,fugle
FINMIND_PUBLIC_FALLBACK_ENABLED=true
FINMIND_MAX_RETRIES=2
FINMIND_BASE_RETRY_DELAY_SECONDS=0.5
FINMIND_MAX_RETRY_DELAY_SECONDS=5.0
FINMIND_TIMEOUT_SECONDS=20.0
FINMIND_CONNECT_TIMEOUT_SECONDS=8.0
FINMIND_CONCURRENCY=5
FUGLE_MAX_RETRIES=2
FUGLE_BASE_RETRY_DELAY_SECONDS=0.5
FUGLE_MAX_RETRY_DELAY_SECONDS=5.0
FUGLE_TIMEOUT_SECONDS=20.0
FUGLE_CONNECT_TIMEOUT_SECONDS=8.0
```

股價歷史、月營收、五年財報與估值快取預設使用 `REDIS_URL`。Redis 無法連線時，系統會略過快取並直接呼叫資料來源；股價歷史會依 `MARKET_PRICE_PROVIDER_ORDER` 嘗試 FinMind 與 Fugle historical candles。`FINMIND_TOKEN` 有設定時會走授權來源；未設定但 `FINMIND_PUBLIC_FALLBACK_ENABLED=true` 時會明確標示為 FinMind public/limited 模式繼續抓資料，避免把「沒有 token」誤判成完全沒有財務資料能力。正式部署若不想依賴 public quota，可設定 `FINMIND_PUBLIC_FALLBACK_ENABLED=false`，此時沒有 token 會直接改走官方最新資料救援或 stale cache。若 FinMind timeout、429/5xx 或傳輸失敗且 `FUGLE_API_KEY` 已設定，會自動改用 Fugle 補股價資料。若 Fugle historical candles 回傳空資料或暫時失敗，系統會再嘗試 Fugle historical stats 補最新交易日快照，但不會把它偽裝成完整歷史 K 線。

若 `MARKET_OFFICIAL_OPENAPI_FALLBACK_ENABLED=true`，FinMind/Fugle 失敗或回傳空資料時，系統會再嘗試 TWSE/TPEx 官方 OpenAPI 補「最新」資料：上市/上櫃最新交易日股價快照、最新月營收、最新一季損益表與資產負債表、最新日 P/E / P/B / 殖利率。這個 fallback 會標示來源如 `TWSE OpenAPI STOCK_DAY_ALL; latest-only` 或 `TPEx OpenAPI mopsfin_t187ap05_O; latest-only`，且只作最新資料救援，不會被包裝成完整五年歷史財務或完整 K 線。FinMind/Fugle 呼叫遇到 429/5xx、timeout 或網路傳輸錯誤時會依各自的 retry 設定與 `Retry-After` / 指數退避重試。若即時資料來源重試後仍失敗或回傳空資料，但 Redis 仍有同股票、同資料集的其他日期區間快取，系統會以 `cached-stale` 標示後暫時救援，避免報告把外部 API 斷線誤判成公司資料不足。報告品質門檻會把 `cached-stale` 列為快取救援資料、把 `latest-only` 列為官方最新救援資料，並降為謹慎判讀；個股估值也不會用 stale 估值直接判定「目前低估」；自動補強會把 stale metrics 轉成刷新任務，若刷新後仍只取得 stale 資料，該任務不會被視為完成。`GET /services/status` 會回傳 `finmind.mode`、`finmind.public_fallback_enabled`、`finmind.data_access_ready`、`fugle`、`market_data_cache.price_provider_order`、`market_data_cache.official_openapi_fallback_enabled`、`market_data_cache.latest_only_source_marker` 與 `market_data_cache.provider_matrix`，方便確認各資料集是授權 FinMind、public/limited FinMind、多來源 fallback，還是官方最新資料救援；`upgrade_capability_matrix.data_business_logic.market_data_provider_fallback` 會把 public/limited FinMind 視為可運作但附上 warning，若正式部署要求授權來源，請同時設定 `FINMIND_TOKEN` 與 `FUGLE_API_KEY`。市場刷新結果也會回傳實際寫入資料的 `sources`，報告品質門檻會列出股價、月營收、五年財務與估值實際入庫來源，避免混合來源時仍顯示成單一 FinMind。

設定公司公開文件抓取：

```bash
COMPANY_FILING_USER_AGENTS=
COMPANY_FILING_PROXY_URLS=
COMPANY_FILING_HTTP_RETRIES=1
COMPANY_FILING_BASE_RETRY_DELAY_SECONDS=0.5
COMPANY_FILING_MAX_RETRY_DELAY_SECONDS=5.0
COMPANY_FILING_PDF_PARSER=auto
COMPANY_FILING_PDF_EXTRACT_TABLES=true
COMPANY_FILING_HTML_EXTRACT_TABLES=true
COMPANY_FILING_CACHE_ENABLED=true
COMPANY_FILING_CACHE_TTL_SECONDS=604800
COMPANY_FILING_BROWSER_RENDER_ENABLED=false
COMPANY_FILING_BROWSER_RENDER_PROVIDER=browserless
COMPANY_FILING_BROWSER_RENDER_URL=
COMPANY_FILING_BROWSER_RENDER_TOKEN=
COMPANY_FILING_BROWSER_RENDER_TIMEOUT_SECONDS=30
COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED=false
COMPANY_FILING_PLAYWRIGHT_BROWSER=chromium
COMPANY_FILING_PLAYWRIGHT_WAIT_UNTIL=networkidle
COMPANY_FILING_PLAYWRIGHT_TIMEOUT_SECONDS=30
COMPANY_FILING_STRUCTURED_API_PROVIDER=
COMPANY_FILING_STRUCTURED_API_URL=
COMPANY_FILING_STRUCTURED_API_TOKEN=
COMPANY_FILING_STRUCTURED_API_TIMEOUT_SECONDS=20
COMPANY_FILING_VISUAL_RAG_ENABLED=true
COMPANY_FILING_VISUAL_RAG_MODE=fallback
COMPANY_FILING_VISUAL_RAG_MODEL=gemini-3.5-flash
COMPANY_FILING_VISUAL_RAG_MAX_PAGES=2
COMPANY_FILING_VISUAL_RAG_DPI=144
COMPANY_FILING_VISUAL_RAG_TIMEOUT_SECONDS=60
```

`COMPANY_FILING_USER_AGENTS` 與 `COMPANY_FILING_PROXY_URLS` 可用逗號或換行設定多組值；系統會依 URL 穩定選用身份與代理，並在 403/429/5xx 重試時往下一組 User-Agent/proxy 偏移，避免同一個被擋身份反覆撞同一入口。若沒有自訂 `COMPANY_FILING_USER_AGENTS`，系統會使用內建 browser-like User-Agent 池，避免公開文件請求以空白或 Python 預設身份送出；`GET /services/status` 會列出 `effective_user_agent_count`、`user_agent_mode`、`user_agent_retry_rotation_enabled`、`proxy_retry_rotation_enabled`、`browser_render_provider` 與 `browser_or_proxy_fallback_configured`，方便分辨目前是只有 UA 偽裝，還是已配置 proxy / Browserless / FlareSolverr / ScrapingBee / BrightData / Playwright 後援。公司文件抓取遇到 403/429/5xx 會依 `COMPANY_FILING_HTTP_RETRIES` 與 `Retry-After` / 指數退避重試。
公司文件抓取錯誤會保留原始 `error`，並額外附上 `category`、`retryable` 與 `stage`。例如 `rate_limited`、`timeout`、`blocked_or_placeholder`、`pdf_no_text`、`company_mismatch`、`document_type_mismatch`、`website_not_found`。自動補強會把這些欄位彙整到每檔公司的 `error_category_counts`、`retryable_error_count` 與 `next_actions`，用來分辨要重試、改走 Proxy 或 Browser render/unlocker、安裝 PDF parser、要求 OCR/人工匯入，或只是公司/文件類型不匹配，避免把爬蟲或 PDF 解析失敗誤寫成公司沒有公開文件。
`COMPANY_FILING_PDF_PARSER=auto` 會優先嘗試表格解析能力較好的 `pdfplumber` / `unstructured`，若未安裝或解析失敗再回到 `pypdf`；其中 `pdfplumber` 已列入基礎依賴，讓一般安裝就具備 PDF 表格抽取能力。解析後文字會加入 `[PDF 解析資訊]` 標記，記錄實際 parser、auto/configured 模式與是否抽取表格。HTML/IR 網頁若含財務表格，`COMPANY_FILING_HTML_EXTRACT_TABLES=true` 會額外加入 `[HTML 表格抽取]` 區塊，把表格列欄保留下來供 RAG 檢索。若要再啟用 `unstructured[pdf]` 進階 parser，可安裝：

```bash
pip install -e ".[dev,pdf]"
```

若 PDF 是掃描圖檔、跨頁表格或排版複雜到文字 parser 容易錯位，可啟用 Visual RAG 後援。`COMPANY_FILING_VISUAL_RAG_ENABLED=true` 會讓 PDF 解析在文字抽取失敗時，把前幾頁轉成圖片交給 vision-capable LLM 萃取可檢索文字；`COMPANY_FILING_VISUAL_RAG_MODE=augment` 則會在文字/表格 parser 成功後額外附加 VLM 表格萃取結果。此能力需要 PyMuPDF renderer 與支援圖片輸入的 LLM model/API key，可安裝：

```bash
pip install -e ".[dev,visual]"
```

萃取結果會加入 `[Visual RAG 解析資訊]` 標記，記錄 mode、renderer、頁數、model、觸發原因與 observability 摘要；`GET /services/status` 與 upgrade audit 會回傳 `visual_rag` runtime，讓部署前能分辨是尚未啟用、缺 PyMuPDF，還是缺 vision LLM key。調整 VLM prompt 或模型順序後，可用 `.venv/bin/python scripts/evaluate_visual_rag.py --golden data/visual_rag_golden.jsonl --results visual_results.json --fail-under 1.0` 對已產出的抽取文字做 golden-set 比對；此評估不會呼叫 LLM，因此不消耗 Gemini 免費額度。

公司公開文件 URL 匯入會把已解析完成的 HTML/PDF 文字快取到 Redis，預設保留 7 天；cache key 會依 URL、PDF parser、PDF 表格抽取與 HTML 表格抽取設定分開，避免切換解析器後誤用舊文本。若 Redis 暫時不可用，系統會自動退回即時抓取；`GET /services/status` 會顯示 `company_filings.cache_available`、`cache_backend`、`cache_key_namespace` 與 `cache_key_scope`，方便確認資料補抓快取是否真的可用。
若 `COMPANY_FILING_BROWSER_RENDER_ENABLED=true` 且 `COMPANY_FILING_BROWSER_RENDER_URL` 有設定，系統在直接抓取失敗、內容太短、疑似登入/反爬蟲頁或公司/文件類型驗證失敗時，會改呼叫瀏覽器/解鎖服務再解析一次。`COMPANY_FILING_BROWSER_RENDER_PROVIDER` 支援 `browserless` / `generic`、`flaresolverr`、`scrapingbee` 與 `brightdata`：Browserless/generic 維持 POST JSON `{"url": "...", "waitUntil": "networkidle0"}` 或 `{url}` template GET；FlareSolverr 會 POST `{"cmd":"request.get","url":"...","maxTimeout":...}` 並讀取 `solution.response`；ScrapingBee 會用 GET params `url`、`render_js=true` 與 `api_key`；BrightData 會用 Bearer token 與 JSON `{"url":"...","format":"raw"}`。`docker-compose.yml` 內建 Browserless Chromium，並提供 optional `unlocker` profile 的 FlareSolverr：本機可用 `docker compose --profile unlocker up -d flaresolverr` 啟動後設定 `COMPANY_FILING_BROWSER_RENDER_PROVIDER=flaresolverr`、`COMPANY_FILING_BROWSER_RENDER_URL=http://127.0.0.1:8191/v1`；compose 服務內則可用 `http://flaresolverr:8191/v1`。`.venv/bin/python scripts/start_system.py --start-dependencies` 會啟動 Browserless 3000 port 並在本次程序中套用 `COMPANY_FILING_BROWSER_RENDER_URL=http://127.0.0.1:3000/content?token=...`；`GET /services/status` 會實際檢查 render URL host/port 是否連得上，只有 endpoint reachable 才把 render 後援列為已配置，避免只填了 URL 就誤判為正式可用。若不想架 Browserless，也可以安裝 `pip install -e ".[dev,browser]"` 後執行 `python -m playwright install chromium`，再設定 `COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED=true`，讓本機 Playwright 在直接抓取失敗時渲染 IR/公開文件頁；`GET /services/status` 會顯示 `playwright_render_dependency_available`、`playwright_render_browser_available`、`playwright_render_runtime` 與 `playwright_render_configured`，且必須套件與指定瀏覽器 binary 都可用才會把 Playwright 後援列為已配置。若已安裝 browser extra 且瀏覽器 binary 存在，一鍵啟動在未配置 Browserless/Proxy 時也可臨時套用 `COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED=true`；不改寫 `.env`。
若有 TEJ 或其他專業財經資料 API，可設定 `COMPANY_FILING_STRUCTURED_API_PROVIDER=tej`、`COMPANY_FILING_STRUCTURED_API_URL` 與 `COMPANY_FILING_STRUCTURED_API_TOKEN`。系統會在公司文件 discovery 階段先呼叫該 JSON API，再接續 Google News/官方網站搜尋；API contract 為 GET JSON，支援 `documents` / `data` / `results` 陣列，每筆可含 `title`、`text` / `content` / `summary`、`url`、`publisher`、`published_at`、`document_type`。`GET /services/status` 與 upgrade audit 會把 `company_filing_structured_api_fallback` 列為外部部署選項，適合把法說會簡報、重大訊息或被 MOPS/IR 擋住的文件改走穩定授權來源。

設定工作流引擎：

```bash
WORKFLOW_ENGINE=local
WORKFLOW_LOCAL_FALLBACK_ENABLED=true
PREFECT_API_URL=
TEMPORAL_ADDRESS=localhost:7233
TEMPORAL_NAMESPACE=default
TEMPORAL_TASK_QUEUE=stock-analysis
TEMPORAL_WORKFLOW_NAME=StockAnalysisPipeline
TEMPORAL_UI_URL=
TEMPORAL_TIMEOUT_SECONDS=15.0
AIRFLOW_API_URL=
AIRFLOW_DAG_ID=stock_analysis_pipeline
AIRFLOW_API_TOKEN=
AIRFLOW_USERNAME=
AIRFLOW_PASSWORD=
AIRFLOW_TIMEOUT_SECONDS=15.0
```

`local` 會使用 analysis run payload 內的 workflow checkpoint。若切換為 `prefect`、`temporal` 或 `airflow`，`GET /services/status` 會顯示 `workflow_orchestration.ready`、缺少的套件或設定；`POST /pipeline/run` 與 `POST /pipeline/run_discovered` 會先經過 workflow runner。Prefect 依賴可用時會以 flow 包裝執行並在回傳中標示 `workflow_orchestration.executed_engine=prefect`；Temporal 設定完整時會以 `TEMPORAL_WORKFLOW_NAME` start workflow，把 `operation`、原始 request 或 resume `run_id` 傳給 worker，並回傳 `workflow_orchestration.external_run_id` / `external_url`；Airflow 設定完整時會呼叫 `POST /api/v1/dags/{AIRFLOW_DAG_ID}/dagRuns`，把同樣的 dispatch payload 放入 DAG run `conf`，並回傳外部 run id 供 UI 追蹤；外部 engine 未就緒時，開發環境預設會明確標示 `local_checkpoint_fallback`，不假裝已外部派發。正式環境可設 `WORKFLOW_LOCAL_FALLBACK_ENABLED=false`，讓 pipeline 在外部工作流不可用時直接回報 503，避免補強/重跑流程看似成功但實際未由指定引擎接管。pipeline 完成後會把 `workflow_orchestration` metadata 合併寫回對應 analysis run payload，因此 `GET /runs`、`GET /runs/{id}` 與 linked task run 會額外回傳 `workflow_orchestration` 與 `workflow_summary`；`workflow_summary` 包含完成比例、失敗/執行中/待處理步驟數、`resume_from_step` 與可讀的 `resume_hint`，讓前端不用解析整包 payload 也能顯示斷點續跑狀態。標準報告 workflow 可透過 `POST /pipeline/runs/{run_id}/resume` 以同一個 run id 從 `workflow_summary.resume_from_step` 續跑；若 `pre_report_refresh` 已完成，續跑會重用 checkpoint 中的已抓資料摘要，從 `report_build` 或 `auto_follow_up` 接續。探索式主題 workflow 會把 topic discovery、source ingestion、candidate revalidation 與 market data refresh 的 stage artifacts 寫回 checkpoint；若 `topic_discovery` 失敗，會使用同一個 run 的原始主題重新拆題並接續後續流程；若 `source_ingestion` 失敗，會沿用已保存的拆題結果與抓取設定繼續抓資料；若 `candidate_revalidation`、`market_data_refresh` 或 `report_build` 失敗，可用已保存的新聞文件、候選名單、來源審計與市場資料接續重建報告；若後續 `auto_follow_up` 失敗，可透過 `POST /pipeline/discovered-runs/{run_id}/resume` 從同一份已產出的報告接續補強流程。缺少必要 stage artifacts 時仍會明確拒絕續跑，避免用不完整資料重建報告。

外部 Airflow/Temporal worker 收到 dispatch payload 後，應呼叫 `POST /pipeline/worker/execute`，把 `operation`、`request` 或 `run_id` 原樣傳入。這個 endpoint 會直接執行本機 pipeline 並標示 `workflow_orchestration.mode=external_worker_local_execution`，不會再經過 workflow runner，避免 worker 回打一般 pipeline endpoint 時重新派發到外部引擎造成遞迴。

啟動 API：

一鍵啟動 API、Streamlit 與本機依賴服務：

```bash
.venv/bin/python scripts/start_system.py --open-browser --start-dependencies
```

若第一次啟動時本機尚未有 Neo4j / Browserless image，一鍵啟動會先停在 `需下載` 並提示 `docker compose pull neo4j browserless`，避免安靜卡在 Docker pull。確認網路與 Docker Desktop 正常後，可先手動 pull，或改用 `.venv/bin/python scripts/start_system.py --start-dependencies --pull-missing-dependencies` 允許啟動流程自動下載；自動下載會先逐一 pull 缺少的 service image，再重新檢查 image 是否存在，若 Docker Desktop 網路或 registry 逾時，訊息會指出卡在哪一個 service。若 Browserless 尚未就緒但本機 Playwright 套件與 Chromium binary 已安裝，一鍵啟動會在本次程序把公司文件渲染後援切到 Playwright，不必等待 Browserless image 完成下載。

升級目標稽核：

```bash
.venv/bin/python scripts/upgrade_audit.py
.venv/bin/python scripts/upgrade_audit.py --json
.venv/bin/python scripts/upgrade_audit.py --strict-external
.venv/bin/python scripts/upgrade_audit.py --strict-external --local-neo4j-defaults --wait-local-neo4j 20
```

`upgrade_audit.py` 會讀取 `GET /services/status` 同源的能力矩陣，逐項檢查 multilingual embedding、LLM SDK/fallback、hybrid search、reranking、LLM/RAG observability、Visual RAG/VLM 財報解析、GraphRAG/Neo4j payload、API 分層、workflow、Alembic、外部密鑰掃描工具整合、Redis cache、市場資料 fallback、公司文件反爬蟲/表格解析、PDF 表格 parser runtime、結構化公司文件 API 備援與來源可信度分層。預設會把 live Neo4j import、Visual RAG、PDF 表格 parser runtime、Proxy/Browser render/Playwright 後援與結構化文件 API 視為外部部署選項，因此未設定 `NEO4J_URI`、未啟用 Visual RAG 或未安裝 `pdfplumber` / `unstructured[pdf]` 只列 warning；若正式部署要求這些外部能力，請加 `--strict-external`，此時外部整合未就緒會讓稽核失敗。
本機 Docker 開發時，可加 `--local-neo4j-defaults` 暫時套用 docker-compose 的 Neo4j URI/帳密到這次稽核程序，並用 `--wait-local-neo4j 20` 等待 `localhost:7687`；若也要驗證 Browserless，可加 `--wait-local-browserless 20 --local-browser-render-defaults` 等待 `localhost:3000` 後臨時套用本機瀏覽器渲染 URL。若不想觸發下載，只想確認本機是否已有必要 image，可加 `--check-local-docker-images`，稽核會回傳 `local_docker_images`，列出 `neo4j:5-community` 與 `ghcr.io/browserless/chromium:latest` 是否已存在。這些設定都不會改寫 `.env`，也不會在 JSON 中輸出密碼值。
同一份稽核也可透過 API 查詢：`GET /services/upgrade-audit` 回傳預設稽核，`GET /services/upgrade-audit?strict_external=true` 會把外部 Neo4j 匯入連線納入必備項目，適合作為部署前檢查。
一鍵啟動會使用同一套稽核輸出 preflight 摘要；若要把外部整合也列為必須通過，可執行 `.venv/bin/python scripts/start_system.py --start-dependencies --strict-upgrade-check`。搭配 `--start-dependencies` 時，啟動程式會先等本機 Neo4j 7687 與 Browserless 3000 連線埠短暫就緒再跑稽核，降低 Docker 剛啟動時的誤判。
若 Neo4j 或 Browserless image 下載較慢，或服務尚未完成啟動，一鍵啟動會在結果中標示 `Neo4j 7687：尚未就緒` / `Browserless 3000：尚未就緒`，並提示用 `docker compose ps`、`docker compose logs neo4j`、`docker compose logs browserless` 或 `docker compose pull neo4j browserless` 查明是下載、啟動還是連線問題。

```bash
.venv/bin/python -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```

啟動 Streamlit：

```bash
.venv/bin/python -m streamlit run streamlit_app.py
```

`streamlit_app.py` 是薄入口；主要 UI 已拆到 `pages/` 與 `app/ui/`，其中 `dashboard_core.py` 放共用 renderer/helper，`analysis_workspace.py`、`report_center.py`、`data_enrichment.py` 與 `system_settings.py` 分別對應四個頁面，`streamlit_dashboard.py` 只保留相容 facade。自訂樣式集中在 `app/ui/styles/stock_dashboard.css`，分析、資料刷新、公司文件 URL 匯入、RSS 抓取與報告補強會先送到 FastAPI/Celery，再從 Streamlit 以 task id 查詢狀態，避免前端等待長時間爬蟲或報告生成。若未來要支援更多同時使用者或更複雜的報告互動，建議保留目前 FastAPI/Celery API 邊界，把前端替換為 Next.js 或 Nuxt，讓 HTML 報表 renderer、互動篩選與背景任務輪詢由現代前端框架接手。

專案已設定 Streamlit 監聽 `0.0.0.0:8501`。同一個區域網路內的手機可用電腦 IP 開啟，例如 `http://192.168.1.117:8501`。
若手機仍無法連線，請確認啟動指令沒有覆蓋成 `--server.address 127.0.0.1`，並允許 macOS 防火牆讓 Python/Streamlit 接受傳入連線。

一鍵啟動會依 `data/schedule_config.json` 自動啟動 Celery worker + beat；預設排程為台北時間每日 16:30 執行 `latest_report_update`，會針對最新報告與候選名單股票強制刷新收盤後市場資料、月營收、五年財務、估值與公司公開文件，並在刷新後重新產生報告。若只需要單獨啟動背景排程，可使用：

```bash
.venv/bin/python -m celery -A app.tasks.celery_app.celery_app worker -B --loglevel=INFO --pool=solo
```

Docker Compose 也提供獨立 worker 與 beat：

```bash
docker compose up -d celery-worker celery-beat
```

## 常用 API

- `GET /health`
- `GET /db/status`
- `GET /services/status`
- `GET /services/upgrade-audit`
- `GET /supply-chain/graph`
- `GET /supply-chain/graph/reasoning`
- `GET /supply-chain/graph/cypher-plan`
- `GET /supply-chain/graph/cypher-query`
- `GET /supply-chain/graph/neo4j`
- `POST /supply-chain/graph/neo4j/import`
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
- `POST /pipeline/worker/execute`：外部 Airflow/Temporal worker 用 dispatch payload 執行本機 pipeline，避免二次派發
- `POST /pipeline/runs/{run_id}/resume`
- `POST /pipeline/discovered-runs/{run_id}/resume`
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

## 維護與 Smoke 測試

建立本機備份可執行 `.venv/bin/python scripts/system_backup.py create --json`；預覽而不寫入則加 `--dry-run`。SQLite 開發資料庫會被複製到 `backups/`，`reports/` 內的報告檔會一起保存；若 `DATABASE_URL` 指向 PostgreSQL 等外部資料庫，工具會在 manifest 中標示 `external_dump_required` 並提示用部署資料庫工具（例如 `pg_dump`）產生 dump。復原預設只做 dry-run：`.venv/bin/python scripts/system_backup.py restore backups/<backup_dir> --json`，確認操作後才加 `--apply`。

服務啟動後可跑 `.venv/bin/python scripts/frontend_smoke.py --json`，它會檢查 Streamlit 首頁、FastAPI `/services/status`，並在 Playwright 可用時截圖到 `artifacts/frontend_smoke/streamlit.png` 且驗證畫面不是空白 PNG。CI 或沒有瀏覽器 binary 的環境可加 `--skip-browser`，保留 HTTP smoke。

## 升級稽核

部署前建議執行：

```bash
.venv/bin/python scripts/upgrade_audit.py --json
```

核心檢查失敗時 CLI 會回傳非 0 exit code；只有外部選配能力（目前為 live Neo4j import，以及公司文件 Proxy / Browser render / Playwright 後援）未設定時，預設回傳 0 但標示 `caution`。CLI、API 與維護頁會同時顯示 `implementation`（核心升級）與 `deployment`（外部整合）狀態，因此可分辨是分析/RAG/資料邏輯尚未就緒，還是 Neo4j、瀏覽器渲染或代理這類正式部署服務尚未啟動。搭配 `--strict-external` 可把外部整合也列為必須通過。
本機部署檢查可加上 `.venv/bin/python scripts/upgrade_audit.py --local-neo4j-defaults --wait-local-neo4j 20 --wait-local-browserless 20 --local-browser-render-defaults --json`，在不改 `.env` 的情況下套用 docker-compose Neo4j 預設值；若本機 Browserless 3000 已啟動或在等待時間內就緒，會優先套用 Browserless URL，否則只有在 Playwright 套件與指定瀏覽器 binary 都可用時，才會啟用公司文件本機瀏覽器後援。

## 自動補強邏輯

報告產生後，系統會把品質門檻、監控清單與重新研究條件轉成可執行任務。任務分成兩類：

- `required`：資料缺口補強，例如缺股價、月營收、五年財務、估值或來源不足。
- `tracking`：追蹤更新，例如資料品質可用，但監控條件要求重新確認股價、月營收或近況訊號。

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
- `app/ui/` 與 `pages/`：Streamlit 多頁面 UI、頁面模組、報告 HTML renderer 與外部 CSS
- `app/tasks/`：Celery app 與背景任務
- `data/`：公開設定、RSS 來源、靜態 AI 產業鏈白名單
- `tests/`：單元與整合測試
- `streamlit_app.py`：Streamlit 入口檔，載入分析工作區首頁

## 後續擴充

- 以 `GET /services/status` 的 `upgrade_capability_matrix` 作為部署前檢查清單，優先處理標為 `degraded` 或 `not_configured` 的能力，例如未安裝 embedding/reranker 依賴、Redis 未連線、Neo4j 未設定或本機資料庫尚未 stamp/upgrade 到 Alembic head。
- 逐步將正式部署預設改為 `DATABASE_INIT_MODE=alembic`，並為既有 SQLite / PostgreSQL 環境提供 migration stamp 腳本。
- 擴充主題無關的台股公司 universe，讓 AI 能在不同主題下建立候選清單。
- 加入報告版本比較、回測與投資組合追蹤。
