# Deployment Readiness Runbook

本文件集中放外部部署、公司文件抓取、GraphRAG/Neo4j、Visual RAG 與 smoke test 操作細節。README 只保留快速入口，避免主要專案說明被部署排障流程淹沒。

## Local Dependencies

啟動核心本機依賴：

```bash
docker compose up -d redis postgres neo4j browserless chroma
```

本機 Chroma 對外 port 使用 `8001`，避免和 FastAPI 的 `8000` 衝突；主機端若要使用 Chroma HTTP server，可設定 `USE_CHROMA=true` 與 `CHROMA_API_URL=http://127.0.0.1:8001`。compose 服務內仍使用 `http://chroma:8000`。Docker Compose 會對 Browserless `/json/version`、Chroma `/api/v2/heartbeat` 與 FlareSolverr `/health` 做 healthcheck。

Docker Compose 的 app / Celery 共用同一組 runtime env contract：Gemini / OpenAI / Anthropic / Cohere key、LLM 模型順序與免費額度、RAG embedding/reranker、FinMind/Fugle token、公司文件 structured API、Visual RAG、LangSmith/Phoenix observability、workflow engine 與 sync-report/recovery policy 都可由 `.env` 或 host env 覆蓋後傳入 worker/beat。涉及服務 DNS 的 URL 需分 host-only 與 compose 內部位址，例如主機端用 `127.0.0.1`，compose worker 內用 service name。

若公開資訊觀測站或公司 IR 入口遇到 Cloudflare / CAPTCHA / 空殼頁，可額外啟動 FlareSolverr unlocker profile：

```bash
docker compose --profile unlocker up -d flaresolverr

# Host-only local process, for example start_system.py or shell smoke:
COMPANY_FILING_BROWSER_RENDER_PROVIDER=flaresolverr
COMPANY_FILING_BROWSER_RENDER_URL=http://127.0.0.1:8191/v1

# Docker Compose service:
COMPANY_FILING_BROWSER_RENDER_PROVIDER=flaresolverr \
COMPANY_FILING_BROWSER_RENDER_URL=http://flaresolverr:8191/v1 \
docker compose --profile unlocker up -d flaresolverr celery-worker celery-beat
```

一鍵啟動遇到本機尚未有 Redis / Postgres / Neo4j / Browserless / Chroma image 時，會先停在 `需下載` 並提示 `docker compose pull redis postgres neo4j browserless chroma`。確認網路與 Docker Desktop 正常後，可先手動 pull，或改用：

```bash
.venv/bin/python scripts/start_system.py --start-dependencies --pull-missing-dependencies
```

若 Browserless 或 FlareSolverr pull 逾時但本機 Playwright 可用，啟動流程會略過該 render 選配服務、標示 `部分啟動`，並繼續啟動已可用的 Redis / Postgres / Neo4j / Chroma。遇到 MOPS / IR 入口被 Cloudflare、CAPTCHA 或空殼頁擋住時，可加 `--prefer-unlocker`。

## GraphRAG And Neo4j

常用 Neo4j env：

```bash
NEO4J_URI=neo4j://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=stock_ai_neo4j_password
NEO4J_DATABASE=neo4j
NEO4J_TIMEOUT_SECONDS=15.0
NEO4J_STATUS_CHECK_CONNECTION=true
```

本機可用 `docker compose up -d neo4j` 啟動 Neo4j，或用 `start_system.command` / `.venv/bin/python scripts/start_system.py --start-dependencies` 一次啟動 Redis、Postgres、Neo4j 與 Browserless。一鍵啟動會在本次程序中自動套用 docker-compose 的 Neo4j 預設環境變數，不改寫 `.env`。

主機端 `.env` 的 `NEO4J_URI` 可維持 `neo4j://localhost:7687`；compose 服務內部若要改 Neo4j 位址或密碼，請用 `COMPOSE_NEO4J_URI`、`COMPOSE_NEO4J_USER`、`COMPOSE_NEO4J_PASSWORD`、`COMPOSE_NEO4J_DATABASE` 與 `COMPOSE_NEO4J_AUTH`，避免 container 讀到 host-only localhost。

GraphRAG 相關端點：

- `GET /supply-chain/graph`：輸出 retrieval hints 與 `retrieval_plan`。
- `GET /supply-chain/graph/reasoning`：輸出 shortest-path reasoning context 與 Cypher template。
- `GET /supply-chain/graph/cypher-plan`：建立 guarded LLM Cypher plan，只接受 read-only、Company label、白名單關係、參數化與受控深度。
- `GET /supply-chain/graph/cypher-query`：在 Neo4j 已設定時執行 read-only 查詢，未設定時回 validated plan 與 `not_configured`。
- `GET /supply-chain/graph/neo4j`：輸出可匯入 Neo4j 的 Cypher statements 與參數。
- `POST /supply-chain/graph/neo4j/import`：在已設定 Neo4j driver 與連線時匯入目前圖譜。

常用 smoke：

```bash
.venv/bin/python -m scripts.import_supply_chain_graph_neo4j --dry-run --tickers 2330
.venv/bin/python scripts/neo4j_graphrag_smoke.py --tickers 2330 --target-ticker 2382 --question 上下游衝擊 --json
.venv/bin/python scripts/neo4j_graphrag_smoke.py --local-neo4j-defaults --tickers 2330 --target-ticker 2382 --question 上下游衝擊 --json
.venv/bin/python scripts/neo4j_graphrag_smoke.py --tickers 2330 --target-ticker 2382 --question 上下游衝擊 --import-first --json
```

Docker registry 下載 Neo4j image 卡住時，也可用 Homebrew 路徑：`brew install neo4j`、`neo4j-admin dbms set-initial-password stock_ai_neo4j_password`、`brew services start neo4j`。

## External Deployment Smoke

集中檢查外部部署接點：

```bash
.venv/bin/python scripts/external_integrations_smoke.py --json
.venv/bin/python scripts/external_integrations_smoke.py --local-neo4j-defaults --wait-local-neo4j 20 --json
.venv/bin/python scripts/external_integrations_smoke.py --local-browser-render-defaults --prefer-unlocker --wait-local-flaresolverr 20 --json
.venv/bin/python scripts/external_integrations_smoke.py --strict --json
```

`--strict` 適合正式部署前使用，會要求 Neo4j live query/import、Browser/Proxy fallback 與結構化文件 API 等外部整合就緒。

外部 env gap 工具：

```bash
.venv/bin/python scripts/external_deployment_env_gaps.py --env-template
.venv/bin/python scripts/external_deployment_env_gaps.py --env-template --env-template-target compose
.venv/bin/python scripts/external_deployment_env_gaps.py --env-check --env-file .env
.venv/bin/python scripts/external_deployment_env_gaps.py --env-check --env-check-target all --env-file .env
```

FastAPI 也提供 `GET /services/external-deployment/env-check?target=all`。檢查輸出會隱藏 token、password 與 API key 實值，只顯示 set/unset/different；template 會把 token、password 與 API key 行預設註解，避免 placeholder 被當成真實 secret 載入。

## Company Filings, PDF, And Unlockers

常用公司文件 env：

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
COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED=true
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

`COMPANY_FILING_USER_AGENTS` 與 `COMPANY_FILING_PROXY_URLS` 可用逗號或換行設定多組值；系統會依 URL 穩定選用身份與代理，並在 403/429/5xx 重試時往下一組 User-Agent/proxy 偏移。公司文件抓取錯誤會保留原始 `error`，並額外附上 `category`、`retryable` 與 `stage`，讓補強流程能分辨重試、改走 browser/unlocker、安裝 PDF parser、設定 Visual RAG、等待 VLM 額度或人工匯入。

`COMPANY_FILING_PDF_PARSER=auto` 會優先嘗試 `pdfplumber` / `unstructured`，若未安裝或解析失敗再回到 `pymupdf`，最後才使用 `pypdf`。若要再啟用 `unstructured[pdf]` 進階 parser 與 PyMuPDF 文字 fallback：

```bash
pip install -e ".[dev,pdf]"
```

Visual RAG 用於掃描圖檔、跨頁表格或複雜排版 PDF。此能力需要 PyMuPDF renderer 與支援圖片輸入的 LLM model/API key；Imagen、embedding、Live/audio 與 Gemma text fallback 不會被視為可用的 PDF 圖片理解模型。

```bash
pip install -e ".[dev,visual]"
.venv/bin/python scripts/evaluate_visual_rag.py --golden data/visual_rag_golden.jsonl --results visual_results.json --fail-under 1.0
```

`COMPANY_FILING_BROWSER_RENDER_PROVIDER` 支援 `browserless` / `generic`、`flaresolverr`、`scrapingbee` 與 `brightdata`：

- Browserless/generic：POST JSON `{"url": "...", "waitUntil": "networkidle0"}` 或 `{url}` template GET。
- FlareSolverr：POST `{"cmd":"request.get","url":"...","maxTimeout":...}` 並讀取 `solution.response`。
- ScrapingBee：GET params `url`、`render_js=true` 與 `api_key`。
- BrightData：Bearer token 與 JSON `{"url":"...","format":"raw"}`。

常用 render/unlocker smoke：

```bash
.venv/bin/python scripts/company_filing_render_smoke.py --url https://example.com/ --json
.venv/bin/python scripts/company_filing_render_smoke.py --local-browser-render-defaults --prefer-unlocker --url https://mops.twse.com.tw/ --json
.venv/bin/python scripts/company_filing_render_smoke.py --provider-contract --json
```

官方重大訊息 OpenAPI fallback 不需要 API key，會先嘗試：

- 上市公司：`https://openapi.twse.com.tw/v1/opendata/t187ap04_L`
- 上櫃公司：`https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O`

若有 TEJ 或其他專業財經資料 API，可設定：

```bash
COMPANY_FILING_STRUCTURED_API_PROVIDER=tej
COMPANY_FILING_STRUCTURED_API_URL=<provider-json-endpoint>
COMPANY_FILING_STRUCTURED_API_TOKEN=<token>
```

免費版可先用 bundled sample 與本機 fixture 驗證 contract：

```bash
.venv/bin/python scripts/structured_company_filing_smoke.py --sample-json examples/structured_company_filing_sample.json --ticker 2330 --company-name 台積電 --document-type investor_presentation --json
.venv/bin/python scripts/structured_company_filing_fixture_smoke.py --json --strict
.venv/bin/python scripts/structured_company_filing_fixture_smoke.py --provider-profile tej --json --strict
.venv/bin/python scripts/local_structured_company_filing_api.py --sample-json examples/structured_company_filing_sample.json --host 127.0.0.1 --port 8794
COMPANY_FILING_STRUCTURED_API_PROVIDER=custom COMPANY_FILING_STRUCTURED_API_URL=http://127.0.0.1:8794/filings .venv/bin/python scripts/structured_company_filing_smoke.py --ticker 2330 --company-name 台積電 --document-type investor_presentation --json
```

只有需要穩定法說會簡報、完整重大訊息歷史或被 MOPS/IR 擋住的文件時，才需要接 TEJ、ScrapingBee dataset、BrightData dataset 或 custom live API。

## Upgrade Audit

常用稽核指令：

```bash
.venv/bin/python scripts/upgrade_audit.py
.venv/bin/python scripts/upgrade_audit.py --json
.venv/bin/python scripts/upgrade_audit.py --auto-local-defaults --json
.venv/bin/python scripts/upgrade_audit.py --strict-external
.venv/bin/python scripts/upgrade_audit.py --strict-external --local-neo4j-defaults --wait-local-neo4j 20
```

預設模式只把外部選配列為 `optional_warnings`，不拉低一般稽核的 `overall_status`。`--strict-external` 會把外部整合也列為必須通過，適合正式部署前檢查。

本機 Docker 開發時，可先用 `--auto-local-defaults --json` 自動偵測已開啟的 localhost Neo4j、Chroma、Browserless 或 FlareSolverr，並只在本次稽核程序套用對應預設值；它不會啟動服務、不會改寫 `.env`。若要指定等待時間，可加 `--wait-local-neo4j 20`、`--wait-local-chroma 20`、`--wait-local-browserless 20` 或 `--wait-local-flaresolverr 20`。

`GET /services/status` 會同步輸出 `local_dependency_auto_defaults` preview，列出目前 localhost 服務可讓 `--auto-local-defaults` 套用哪些程序內 defaults、對應哪些 optional capability、以及驗證指令。維護頁會用它把 Neo4j/FlareSolverr 這類「服務已啟動但尚未寫入 env」的 optional gap 標成「本機可驗證」。

## Maintenance UI

系統設定頁的「外部部署選配狀態」會把 upgrade audit 的 `failures`、`warnings` 與 `optional_warnings` 中的外部整合項目列成表格，先顯示外部部署啟用摘要，再用 `external_deployment_local_projection` 扣掉已偵測本機 defaults 可處理的項目，顯示有效剩餘與剩餘付費 API。

維護頁也會顯示：

- Neo4j payload/import、GraphRAG live Cypher、公司文件 render fallback、高風險 MOPS/TWSE/TPEx unlocker 與結構化文件 API 的單項 smoke 指令。
- 本機依賴操作 catalog 的 `resolves_capabilities`、後續診斷、runtime settings cache 清除結果。
- `GET /services/external-deployment/env-check` 的 host/compose env check summary，token、password 與 API key 只顯示 `<set>` / `<unset>`。
- `GET /reports/observability/summary?limit=20` 的 LLM latency、retrieval latency、token/cost、fallback、reranker 與 GraphRAG path coverage。
- `GET /tasks/summary?days=7` 與 `GET /tasks/{task_id}` 的 Celery/API run 成功率、失敗診斷、retry endpoint 與 execution context。

背景任務 no-op 診斷建議使用：

```bash
.venv/bin/python scripts/task_submission_smoke.py --json
.venv/bin/python scripts/task_submission_smoke.py --submit --wait --timeout 30 --json --strict
```
