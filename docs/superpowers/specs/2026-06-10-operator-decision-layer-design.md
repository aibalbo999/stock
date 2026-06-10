# Operator Decision Layer UI/UX Design

Date: 2026-06-10
Approved direction: 決策指揮台 + 報告生命週期 + 事件收件匣

## Context

The current Streamlit app already has an operator-first first screen:

- `分析工作區` shows `今日狀態` with system, latest report, AI quota, and pending action cards.
- `報告中心` shows the latest-report health strip.
- `資料補強` explains the expected report impact of refresh actions.
- Long-running work is submitted through FastAPI/Celery, not direct Streamlit blocking calls.

The next optimization should go deeper than status visibility. A normal operator should not need to infer what to do from multiple cards, maintenance tables, task rows, and report diagnostics. The UI should make an explicit recommendation, explain why, and route the operator to the safest next action.

## Goals

- Turn operational state into a ranked `Next Best Action`.
- Make latest-report trustworthiness visible through a report lifecycle.
- Convert failures, quota pressure, whitelist blocks, and data gaps into an incident inbox.
- Connect data refresh actions to concrete report gaps and post-refresh follow-up.
- Keep main pages simple for non-maintainer operators while preserving drilldown for advanced diagnostics.
- Avoid model/API quota consumption during ordinary UI rendering.

## Non-Goals

- Do not migrate away from Streamlit in this slice.
- Do not add new paid external providers.
- Do not add new long-running operations just to compute UI state.
- Do not call LLM test endpoints, scraping endpoints, or external data refresh endpoints during render.
- Do not remove existing maintenance, raw task, report, or diagnostics views.
- Do not change latest-report retention semantics.

## Product Model

Use three layers:

1. `首頁：決策指揮台`
   - The first screen answers: `現在最該做什麼？`
   - It shows one primary recommendation and a short ranked list of secondary actions.
   - Every recommendation includes reason, risk, expected impact, and route.

2. `報告中心：報告生命週期`
   - The selected latest report is shown as a lifecycle:
     `資料 → 品質 → 補強 → 重跑 → 可讀`
   - Each stage has a state, blocker, next action, and trust implication.
   - This is the main trustworthiness surface for investment-report readers.

3. `維護/設定：事件收件匣`
   - Failures and warnings are normalized into incidents.
   - The full inbox lives in maintenance/settings.
   - The homepage surfaces only the top 1-3 incidents that change the next action.

`資料補強` becomes the action workbench:

- It shows which report/ticker/gap each refresh action can improve.
- It tells the operator whether a report rerun is recommended after the action completes.

## Core Concepts

### Next Best Action

Purpose:

Rank the current system/report/task/quota state into one operator-facing recommendation.

Output fields:

- `state`: `ready`, `attention`, or `blocked`
- `priority`: integer, lower is more urgent
- `title`: short operator-facing instruction
- `reason`: why this is recommended
- `risk`: what can go wrong if ignored
- `impact`: what this action improves
- `action_label`: button or link text
- `route_hint`: route target such as `report:15`, `data_enrichment`, `settings:maintenance`, `task:<id>`
- `source_ids`: related report ids, task ids, tickers, or model ids

Recommended priority order:

1. Task queue unavailable or worker offline.
2. Stale running task.
3. Latest report missing.
4. Latest report has required data gaps.
5. Latest report has quality caution or zero formal tickers.
6. Follow-up/rerun is running.
7. Retryable task failure that affects the latest report.
8. Current model quota exhausted or in cooldown.
9. Data freshness warning for latest report tickers.
10. Everything is healthy; read latest report or start a new analysis.

### Report Lifecycle

Purpose:

Describe whether the latest report is ready to trust and read.

Stages:

- `data`: required source data exists or has gaps.
- `quality`: quality gate status and formal ticker count.
- `follow_up`: auto/manual follow-up status.
- `rerun`: whether rerun is recommended, running, blocked, or not needed.
- `readable`: whether the report can be treated as the current usable version.

Stage states:

- `done`: stage is complete.
- `attention`: stage has warnings but the report remains readable with caveats.
- `blocked`: report should not be trusted until action is taken.
- `running`: background task is in progress.
- `unknown`: payload is missing or cannot be interpreted.

Report lifecycle summary fields:

- `overall_state`
- `stage_cards`
- `trust_label`
- `trust_explanation`
- `primary_action`
- `route_hint`

### Incident Inbox

Purpose:

Convert technical failures into operator-facing incidents.

Incident fields:

- `id`
- `severity`: `critical`, `warning`, or `info`
- `category`: `quota`, `whitelist`, `task_queue`, `data_source`, `vector_store`, `report_quality`, `runtime_storage`, `unknown`
- `title`
- `impact`
- `next_action`
- `route_hint`
- `retryable`
- `source`: task id, report id, ticker, endpoint, or model id
- `created_at`
- `dedupe_key`

Inbox behavior:

- Group duplicate incidents by `dedupe_key`.
- Sort by severity, latest-report impact, retryability, and recency.
- Keep technical details behind expanders.
- Do not hide critical incidents automatically.
- In the first implementation, `read/ignore` state may stay in Streamlit session state or be omitted if persistent storage is not already available.

### Data Gap Action Map

Purpose:

Make data-enrichment buttons explain what report gap they improve.

Action map fields:

- `report_id`
- `topic`
- `ticker`
- `gap_type`: `price`, `financials`, `valuation`, `filing`, `news`, `rag`
- `action_label`
- `operation`
- `impact`
- `post_action_hint`: for example `補完後建議重跑報告`
- `route_hint`

Mapping:

- `price` -> market refresh
- `financials` -> five-year financial refresh
- `valuation` -> valuation refresh
- `filing` -> company filing fetch
- `news` or `rag` -> manual ingest/RSS/import flow

## Proposed Modules

Create pure helper modules first:

- `app/ui/operator_decisions.py`
  - Builds `Next Best Action` and secondary actions.
  - Depends only on payload dictionaries/lists.
  - No Streamlit imports.

- `app/ui/report_lifecycle.py`
  - Builds lifecycle stage cards and trust summary.
  - No Streamlit imports.

- `app/ui/incident_inbox.py`
  - Normalizes task failures, service warnings, quota issues, and report-quality blockers.
  - No Streamlit imports.

Optional later module:

- `app/ui/data_gap_actions.py`
  - Builds data-gap action map for the data enrichment page.
  - No Streamlit imports.

Expected tests:

- `tests/test_operator_decisions_ui.py`
- `tests/test_report_lifecycle_ui.py`
- `tests/test_incident_inbox_ui.py`
- `tests/test_data_gap_actions_ui.py` if the data gap action map is included in the first implementation plan.

## Page Changes

### 分析工作區

Add a primary recommendation area above or inside the existing `今日狀態` section:

- One primary `Next Best Action` card.
- Up to three secondary action chips/cards.
- Keep the existing four operator status cards below it.

The recommendation area must not make the first viewport feel like a diagnostics wall. It should be concise and action-oriented.

### 報告中心

Upgrade the existing health strip into a lifecycle strip or compact stepper:

- `資料`
- `品質`
- `補強`
- `重跑`
- `可讀`

Show:

- Trust label.
- Trust explanation.
- Primary report action.
- Blocker detail when blocked or attention.

The report content and download buttons remain below this summary.

### 系統設定 / 維護

Add an incident inbox near existing task diagnostics:

- Summary counts by severity.
- Table/card list of incidents.
- Expander for technical details.
- Route hints to report/data enrichment/maintenance.

The homepage should link to this inbox for nontrivial incidents.

### 資料補強

Add a data-gap action map above the existing refresh buttons:

- Latest impacted report.
- Gap type.
- Suggested operation.
- Expected impact.
- Post-action hint.

Keep the existing manual controls and background task submission behavior.

## Error Handling

- If a source endpoint is unavailable, produce an `unknown` or `attention` state with a route to maintenance.
- If report payloads are missing, do not invent readiness; show `尚無法判斷`.
- If task failures are retryable, label them as retryable but do not auto-submit retries.
- If quota state is missing, show `額度未追蹤`, not `ready`.
- If multiple blockers exist, the highest-priority blocker owns the primary recommendation and the others become secondary actions.

## Testing And QA

Unit tests:

- Next action priority ordering.
- Queue blocked beats report readable.
- Required data gap beats ordinary historical failure.
- Formal ticker count `0` remains `0`.
- Retryable payload validation maps to a retry action.
- Quota exhaustion/cooldown maps to wait or fallback guidance.
- Incident deduplication and severity ordering.
- Lifecycle stage output for readable, caution, blocked, follow-up-running, and missing-report cases.

Contract tests:

- New helper files are included in `tests/streamlit_ui_test_helpers.py`.
- Streamlit pages import and call helper functions.
- Required labels/classes/endpoints are present.

Smoke/browser QA:

- First viewport shows one clear primary recommendation.
- Existing four operator status cards still render.
- Report lifecycle appears above report reader content.
- Incident inbox is reachable from maintenance/settings.
- Data gap action map appears before refresh buttons.
- Desktop and mobile layouts do not overlap.
- No raw HTML closing tags render as code blocks.

## Implementation Slices

1. `Slice 1: Next Best Action`
   - Add `operator_decisions.py`.
   - Render primary recommendation on analysis workspace.
   - Add focused unit and contract tests.

2. `Slice 2: Report Lifecycle`
   - Add `report_lifecycle.py`.
   - Upgrade report center health strip.
   - Add lifecycle unit tests and browser QA.

3. `Slice 3: Incident Inbox`
   - Add `incident_inbox.py`.
   - Render full inbox in maintenance/settings and top incidents on homepage.
   - Add incident sorting/dedup tests.

4. `Slice 4: Data Gap Action Map`
   - Add data-gap action helper if needed.
   - Render report-impact action map on data enrichment page.
   - Add tests for operation mapping and post-action hints.

## Acceptance Criteria

- A non-maintainer operator can answer within the first screen:
  - What should I do next?
  - Why?
  - What is the risk if I ignore it?
  - Where do I click?

- A report reader can answer before reading the report:
  - Is this latest report readable?
  - Which lifecycle stage is blocked or cautionary?
  - Are formal tickers actually present?
  - Does it need data follow-up or rerun?

- A maintainer/operator can answer:
  - Which incidents need action?
  - Which are retryable?
  - Which affect the latest report?
  - Which can be ignored for now?

- No UI render path consumes LLM quota, scraping quota, or external data refresh quota.
- Existing background task submission flows remain FastAPI/Celery based.
- Full focused tests, full test suite, frontend smoke, task submission smoke, and browser QA pass before push.

## Notes For Implementation Planning

- Keep helper modules pure and small.
- Prefer existing API payloads before adding backend endpoints.
- If an endpoint is needed later, add it as a lightweight GET summary endpoint only.
- Keep advanced tables in maintenance; the main operator UI should show decisions, not raw diagnostics.
- Browser QA is required because Streamlit markdown can render indented HTML as code blocks.
