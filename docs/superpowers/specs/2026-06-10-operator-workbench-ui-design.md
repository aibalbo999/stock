# Operator Workbench UI/UX Design

Date: 2026-06-10
Approved approach: 保守產品化 Streamlit

## Context

The system already has the core architecture requested by the optimization goal:

- `streamlit_app.py` is a thin Streamlit navigation entrypoint.
- Main pages live under `pages/` and render through `app/ui/`.
- Long-running work is submitted through FastAPI/Celery background tasks.
- Custom app CSS is centralized in `app/ui/styles/stock_dashboard.css`.
- Latest-per-topic report retention is active, so the report center only needs to foreground the latest usable version.

The remaining UI/UX problem is operational clarity. A normal operator can run the system, but must mentally combine status from the analysis page, report center, data enrichment page, system settings, maintenance panels, task diagnostics, and AI quota tables. The redesign should make the first screen answer:

1. Can I safely run or refresh data right now?
2. Which latest report should I read or improve?
3. What failed recently, and what exact action should I take?
4. Which AI model is currently selected, and is free-tier quota likely to block me?

## Goals

- Add an operator-first "today workbench" layer without replacing the current Streamlit MPA.
- Preserve the existing FastAPI/Celery boundary and avoid direct long-running calls from Streamlit.
- Keep latest-report behavior explicit and easy to trust.
- Turn task failures and model quota state into action-oriented operator language.
- Keep advanced maintenance/debug details available, but move them behind progressive disclosure.
- Make the redesign testable through existing HTTP/API smoke checks, Streamlit import-contract tests, unit tests for UI summary helpers, and browser inspection.

## Non-Goals

- Do not migrate to React/Next.js in this slice.
- Do not change LLM routing policy or consume model quota for UI verification.
- Do not add new paid external integrations.
- Do not remove existing maintenance diagnostics, raw run inspection, or advanced task panels.
- Do not change report retention semantics beyond making "latest only" clearer in the UI.

## Recommended Information Architecture

### Page 1: 分析工作區

Make this page the operator's daily start screen, not only the analysis form.

Top section:

- "今日狀態" summary band.
- Current system readiness from `/services/status`.
- Last task outcome from `/tasks/summary?days=7`.
- Current recommended model from `/llm/quota`.
- Latest report link from `/reports?limit=5`.

Primary operator actions:

- Read latest report.
- Start a new analysis.
- Refresh missing data.
- Retry the most relevant failed task when safe.

The existing analysis form remains on this page, but moves below the status band. Advanced settings stay collapsed.

### Page 2: 報告中心

Keep this as the latest-report reader.

Above the rendered report, add a compact report health strip:

- Latest report title, topic, generated time, and report id.
- Quality gate status if available.
- Candidate count and formal ticker count if available.
- Follow-up state: ready, needs data, blocked, or rerun running.
- One primary action: read, 補強, or retry depending on state.

Keep raw run payloads, delete controls, and task-id debugging inside the existing "疑難排解：執行紀錄" area.

### Page 3: 資料補強

Reframe this page from "choose a data operation" to "fix report data gaps."

Top section:

- Latest report data gaps when available.
- Market cache freshness summary.
- Company filing runtime readiness.

Actions remain the same background data tasks:

- Refresh price.
- Refresh five-year financials.
- Refresh valuation.
- Fetch company filings.
- Manual news or company document ingestion.
- RSS import.

Each action should explain the expected report impact in one short caption.

### Page 4: 系統設定

Keep this as advanced configuration and maintenance.

The maintenance tab remains the home for:

- Full queue/worker diagnostics.
- Upgrade audit detail.
- External deployment optional warnings.
- LLM usage tables.
- Raw task failure drilldown.
- Safe diagnostic actions.

The main pages should link to this area when diagnostics are needed, but should not surface all diagnostic tables by default.

## Components

### `operator_status_summary`

Purpose:

Transform service, task, quota, and report payloads into a small number of operator-facing cards.

Inputs:

- `/services/status`
- `/tasks/summary?days=7&limit=10`
- `/llm/quota`
- `/reports?limit=5`

Output concepts:

- Overall state: `ready`, `attention`, or `blocked`.
- Queue state: worker online, submission ready, processing ready.
- Latest task state: success, running, failed, or unknown.
- AI state: recommended model, remaining requests, cooldown/exhaustion.
- Latest report state: report id, title, generated time, topic.
- Next action label and route hint.

Implementation location:

- Create `app/ui/operator_status.py`.
- Render from `app/ui/analysis_workspace.py`.

### `latest_report_health`

Purpose:

Summarize the currently selected latest report before the reader output.

Inputs:

- `/reports`
- `/reports/{report_id}`
- Existing parsed quality gate and candidate whitelist payloads.
- Existing follow-up plan payload from `/reports/{report_id}/follow-up/plan` when the report is open.

Output concepts:

- Quality gate badge.
- Candidate/formal ticker counts.
- Follow-up readiness.
- Data-gap severity.
- Best next action.

Implementation location:

- Create `app/ui/report_health.py`.
- Render from `app/ui/report_center.py`.

### `task_failure_action_summary`

Purpose:

Convert existing task diagnostics into language for non-maintainer operators.

Inputs:

- `/tasks/summary?days=7&limit=10`.
- Existing helpers in `app/ui/task_failure_diagnostics.py`.

Mapping:

- `payload_validation`: show "輸入或白名單已擋下任務"; if retryable, present "可重試".
- `vector_store`: show "RAG 向量檢索曾降級"; make clear whether current task queue is still usable.
- `runtime_storage`: show "本機檔案或資料庫存取曾失敗"; route to maintenance.
- Unknown failures: show task id, operation, and maintenance route.

Implementation location:

- Add operator-facing summary helpers to `app/ui/operator_status.py`.
- Keep detailed tables in `app/ui/task_failure_diagnostics.py` for maintenance.

### `quota_operator_summary`

Purpose:

Show the current smart-first model choice without exposing every routing field on the main page.

Inputs:

- `/llm/quota`.

Output:

- Recommended model.
- Model order.
- First exhausted/cooldown model if any.
- Remaining request estimate for the current recommended model.
- High-quota fallback model, especially `gemma-4-31b-it`.

Rules:

- Keep the detailed quota table in system settings.
- Do not call `/llm/test` or any endpoint that consumes model quota during ordinary UI render.

## Data Flow

Streamlit render path:

1. Load app CSS through existing `configure_page`.
2. On the analysis workspace, call lightweight GET endpoints:
   - `/services/status`
   - `/tasks/summary?days=7&limit=10`
   - `/llm/quota`
   - `/reports?limit=5`
3. Convert payloads through pure helper functions.
4. Render status cards, action captions, and links/buttons.
5. Submit long-running actions only through existing background task helpers.
6. Poll task status only through `render_task_status_panel` or existing task status endpoints.

No Streamlit page should introduce `asyncio.run`, long synchronous report generation, or direct crawler calls.

## Error Handling

- If `/services/status` is unavailable, show an attention state and direct the operator to system settings maintenance.
- If `/tasks/summary` is unavailable, hide recent task action cards but keep analysis/report actions visible.
- If `/llm/quota` is unavailable, show "模型額度狀態暫不可讀"; do not block report reading.
- If `/reports` is empty, show a clear empty state with "建立分析" as the primary action.
- Historical failures should not make the whole system look broken when current queue readiness and latest smoke task are healthy.
- Optional external deployment warnings should stay marked as optional, not blocking, unless strict external mode is enabled elsewhere.

## Visual Direction

Style:

- Quiet operational dashboard.
- Dense but readable.
- No marketing hero.
- No decorative blobs or oversized illustration sections.

Layout:

- Use compact horizontal status bands on desktop.
- Stack cards vertically on mobile.
- Keep cards at 8px radius or less, matching existing CSS.
- Use existing semantic colors: primary, accent, warning, danger, surface, muted.
- Use tabular numeric presentation where possible for counts, requests, and report ids.

Interaction:

- One primary action per screen section.
- Secondary actions remain available as Streamlit buttons or expanders.
- Use progressive disclosure for diagnostics.
- Disabled actions must have a caption explaining the missing condition.

Accessibility:

- Keep visible labels on inputs.
- Preserve focus-visible styling.
- Do not rely on color alone for readiness or failure.
- Keep button targets at least 44px high, following existing CSS.

## Testing Plan

Unit/contract tests:

- Add tests for operator summary helper functions.
- Add tests for task failure action summaries.
- Extend Streamlit UI contract tests to assert the new helper module and workbench labels exist.
- Ensure no new `asyncio.run` appears in frontend scan paths.

Focused commands:

```bash
.venv/bin/python -m pytest tests/test_streamlit_ui_contract.py tests/test_frontend_smoke.py tests/test_status_frontend.py -q
.venv/bin/python -m pytest tests/test_run_task_observability.py tests/test_llm_quota.py -q
.venv/bin/python -m ruff check app/ui tests/test_streamlit_ui_contract.py
```

Full verification before shipping:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check app tests streamlit_app.py
.venv/bin/python -m compileall app streamlit_app.py
.venv/bin/python scripts/task_submission_smoke.py --submit --wait --json --strict
.venv/bin/python scripts/frontend_smoke.py --streamlit-url http://127.0.0.1:8501 --api-url http://127.0.0.1:8000 --skip-browser --json
```

Browser QA:

- Open `http://127.0.0.1:8501`.
- Verify the first viewport answers system readiness, latest report, recent failure, and AI model state.
- Open the report center and verify the latest report health strip appears above report content.
- Open data enrichment and verify report-impact captions are visible.
- Check desktop and mobile-ish viewports for text overflow and incoherent overlap.

## Implementation Slices After Spec Approval

1. Add pure operator summary helpers and tests.
2. Render the today workbench in `analysis_workspace.py`.
3. Add latest report health strip in `report_center.py`.
4. Reword data enrichment action captions without changing task endpoints.
5. Add CSS for compact status bands and cards.
6. Run browser QA and full verification.

## Approval Gate

This spec documents the approved approach, but implementation should start only after the user reviews this file and confirms it matches the intended operator workflow.
