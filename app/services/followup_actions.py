from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import date, timedelta
from urllib.parse import quote_plus

from app.core.time import today_taipei
from app.db.session import session_scope
from app.models.schemas import ReportRequest
from app.services.ingestion import IngestionPipeline
from app.services.persistence import (
    CompanyFilingRepository,
    FinancialMetricRepository,
    MarketRepository,
    MonthlyRevenueRepository,
    NewsRepository,
    ValuationMetricRepository,
)


ActionType = str
FOLLOW_UP_ACTION_LABELS = {
    "ingest_news": "補抓資料源",
    "ingest_company_filings": "補抓公司公開文件",
    "refresh_market": "刷新股價/量能",
    "refresh_monthly_revenue": "刷新月營收",
    "refresh_financial_metrics": "刷新五年財務",
    "refresh_valuations": "刷新估值",
    "rerun_discovery": "重跑主題拆解",
    "rerun_analysis": "重跑分析報告",
}
TRACKING_FRESHNESS_THRESHOLDS = {
    "refresh_market": 5,
    "refresh_monthly_revenue": 75,
    "refresh_valuations": 14,
    "refresh_financial_metrics": 150,
    "ingest_company_filings": 365,
}
TRACKING_CANDIDATE_LIMIT = 5
FOLLOW_UP_ACTION_CONCURRENCY = 4
FOLLOW_UP_ACTION_TIMEOUT_SECONDS = 90
FOLLOW_UP_NEWS_QUERY_TIMEOUT_SECONDS = 8
FOLLOW_UP_NEWS_FALLBACK_TIMEOUT_SECONDS = 20
FOLLOW_UP_NEWS_WEB_SEARCH_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class FollowUpAction:
    action_type: ActionType
    reason: str
    tickers: tuple[str, ...] = ()
    priority: str = "medium"
    frequency: str = "once"
    purpose: str = "required"

    def key(self) -> tuple[str, tuple[str, ...]]:
        return self.action_type, self.tickers

    def to_dict(self) -> dict:
        return {
            "action_type": self.action_type,
            "label": FOLLOW_UP_ACTION_LABELS.get(self.action_type, self.action_type),
            "reason": self.reason,
            "tickers": list(self.tickers),
            "priority": self.priority,
            "frequency": self.frequency,
            "purpose": self.purpose,
        }


class FollowUpActionPlanner:
    def plan(
        self,
        request: ReportRequest,
        quality_gate: dict | None = None,
        source_audit: dict | None = None,
        markdown: str = "",
        contexts: list[dict] | None = None,
        company_data_audit: dict | None = None,
        candidate_audit_required: bool = True,
        apply_freshness: bool = True,
    ) -> list[FollowUpAction]:
        tickers = tuple(request.tickers)
        actions: list[FollowUpAction] = []
        actions.extend(self.from_quality_gate(quality_gate or {}, tickers))
        actions.extend(self.from_source_audit(source_audit or {}, tickers))
        actions.extend(self.from_company_data_audit(company_data_audit or {}, tickers))
        actions.extend(self.from_monitoring_contexts(contexts or [], tickers))
        actions.extend(self.from_monitoring_markdown(markdown, tickers))
        actions.extend(self.from_candidate_audit_markdown(markdown, tickers, required=candidate_audit_required))
        if actions and not any(action.action_type == "rerun_analysis" for action in actions):
            purpose = "required" if any(action.purpose == "required" for action in actions) else "tracking"
            reason = (
                "補強資料完成後自動重跑分析，讓投資結論反映最新資料。"
                if purpose == "required"
                else "追蹤資料更新後重跑分析，確認投資結論是否需要調整。"
            )
            actions.append(
                FollowUpAction(
                    "rerun_analysis",
                    reason,
                    tickers,
                    "high",
                    "once",
                    purpose,
                )
            )
        actions = dedupe_actions(actions)
        return filter_fresh_tracking_actions(actions, request) if apply_freshness else actions

    def from_source_audit(self, source_audit: dict, tickers: tuple[str, ...]) -> list[FollowUpAction]:
        source_relevance = source_audit.get("source_relevance") or {}
        readiness = source_relevance.get("subtopic_readiness") or {}
        missing = [
            name
            for name, detail in readiness.items()
            if isinstance(detail, dict) and detail.get("status") == "missing"
        ]
        weak = [
            name
            for name, detail in readiness.items()
            if isinstance(detail, dict) and detail.get("status") == "weak"
        ]
        actions: list[FollowUpAction] = []
        if missing:
            actions.append(
                FollowUpAction(
                    "ingest_news",
                    "來源覆蓋審計缺口：缺少來源覆蓋子題：" + "、".join(missing[:6]),
                    (),
                    "high",
                    "weekly",
                    "required",
                )
            )
            actions.append(
                FollowUpAction(
                    "rerun_discovery",
                    "補齊缺來源子題後，重新驗證主題拆解、候選白名單與來源覆蓋。",
                    (),
                    "high",
                    "once",
                    "required",
                )
            )
        elif weak:
            actions.append(
                FollowUpAction(
                    "ingest_news",
                    "來源覆蓋審計缺口：弱來源子題需補不同發布者或缺少的資料意圖：" + "、".join(weak[:6]),
                    (),
                    "medium",
                    "weekly",
                    "required",
                )
            )
        return actions

    def from_quality_gate(self, quality_gate: dict, tickers: tuple[str, ...]) -> list[FollowUpAction]:
        issue_text = "；".join(
            [
                *[str(item) for item in quality_gate.get("blockers") or []],
                *[str(item) for item in quality_gate.get("warnings") or []],
                *[str(item) for item in quality_gate.get("remediation_actions") or []],
            ]
        )
        actions: list[FollowUpAction] = []
        if not issue_text:
            return actions
        if self._has(issue_text, "股價", "成交量", "領先訊號", "近況訊號"):
            actions.append(
                FollowUpAction("refresh_market", "補齊股價歷史、成交量與近況訊號。", tickers, "high", "weekly")
            )
        if self._has(issue_text, "月營收", "營收"):
            actions.append(FollowUpAction("refresh_monthly_revenue", "補齊月營收與成長加速資料。", tickers, "high", "monthly"))
        if self._has(issue_text, "五年財務", "財務指標", "財務資料"):
            actions.append(FollowUpAction("refresh_financial_metrics", "補齊近五年財務資料。", tickers, "medium", "monthly"))
        if self._has(issue_text, "估值", "P/E", "DCF", "同業"):
            actions.append(FollowUpAction("refresh_valuations", "補齊估值與同業比較資料。", tickers, "medium", "weekly"))
        if self._has(issue_text, "資料來源", "來源", "新聞", "國際", "發布者", "時間戳", "近期資料"):
            target_tickers = () if self._has(issue_text, "主題拆解子題", "來源覆蓋子題") else tickers
            actions.append(
                FollowUpAction(
                    "ingest_news",
                    "補抓近期與國際資料源，提高 RAG 證據覆蓋。",
                    target_tickers,
                    "high",
                    "weekly",
                )
            )
        if self._has(issue_text, "AI 拆解任務", "候選公司", "證據驗證", "正式分析股票"):
            actions.append(FollowUpAction("rerun_discovery", "重新執行 AI 主題拆解與候選白名單驗證。", tickers, "high", "once"))
        if self._has(issue_text, "LLM 補充分析", "模型恢復"):
            actions.append(
                FollowUpAction(
                    "rerun_analysis",
                    "LLM 供應商或 API key 恢復後，重新產生報告並保留來源核查。",
                    tickers,
                    "high",
                    "once",
                )
            )
        return actions

    def from_company_data_audit(self, audit: dict, fallback_tickers: tuple[str, ...]) -> list[FollowUpAction]:
        actions: list[FollowUpAction] = []
        for row in audit.get("rows") or []:
            if row.get("status") == "sufficient":
                continue
            ticker = str(row.get("ticker") or "")
            tickers = (ticker,) if ticker else fallback_tickers
            missing_text = "；".join(str(item) for item in row.get("missing") or [])
            if self._has(missing_text, "股價", "成交量"):
                actions.append(FollowUpAction("refresh_market", f"個股資料審計缺口：{missing_text}", tickers, "high"))
            if self._has(missing_text, "月營收"):
                actions.append(FollowUpAction("refresh_monthly_revenue", f"個股資料審計缺口：{missing_text}", tickers, "high"))
            if self._has(missing_text, "五年財報", "核心財報", "財報"):
                actions.append(FollowUpAction("refresh_financial_metrics", f"個股資料審計缺口：{missing_text}", tickers, "medium"))
            if self._has(missing_text, "估值"):
                actions.append(FollowUpAction("refresh_valuations", f"個股資料審計缺口：{missing_text}", tickers, "medium"))
            if self._has(missing_text, "公司原始公開文件", "公開文件"):
                actions.append(
                    FollowUpAction(
                        "ingest_company_filings",
                        f"個股資料審計缺口：{missing_text}",
                        tickers,
                        "high",
                        "monthly",
                        "required",
                    )
                )
            if self._has(missing_text, "公司文本", "公司層級文本", "文本證據", "AI 歸因", "入庫"):
                actions.append(
                    FollowUpAction(
                        "ingest_news",
                        f"個股資料審計缺口：{missing_text}",
                        tickers,
                        "high",
                        "weekly",
                        "required",
                    )
                )
        return actions

    def from_monitoring_contexts(self, contexts: list[dict], fallback_tickers: tuple[str, ...]) -> list[FollowUpAction]:
        actions = []
        for context in contexts:
            label = str(context.get("label") or "")
            ticker = self._extract_ticker(label)
            tickers = (ticker,) if ticker else fallback_tickers
            trigger = "；".join(
                [
                    str(context.get("recheck_trigger") or ""),
                    str(context.get("avoid_trigger") or ""),
                    str(context.get("decision") or ""),
                ]
            )
            actions.extend(self._actions_from_trigger(trigger, tickers))
        return actions

    def from_monitoring_markdown(self, markdown: str, fallback_tickers: tuple[str, ...]) -> list[FollowUpAction]:
        rows = self._markdown_table_rows(markdown, "監控清單", required_headers=("股票", "重新研究條件"))
        actions = []
        for row in rows:
            ticker = self._extract_ticker(row.get("股票", ""))
            tickers = (ticker,) if ticker else fallback_tickers
            trigger = "；".join([row.get("重新研究條件", ""), row.get("繼續避開/觀察條件", "")])
            actions.extend(self._actions_from_trigger(trigger, tickers))
        return actions

    def from_candidate_audit_markdown(
        self,
        markdown: str,
        fallback_tickers: tuple[str, ...],
        required: bool = True,
    ) -> list[FollowUpAction]:
        rows = self._markdown_table_rows(markdown, "候選公司審計", required_headers=("股票", "狀態"))
        if not required:
            rows = self._top_tracking_candidate_rows(rows, TRACKING_CANDIDATE_LIMIT)
        actions: list[FollowUpAction] = []
        weak_or_missing = []
        purpose = "required" if required else "tracking"
        priority = "high" if required else "medium"
        for row in rows:
            status = row.get("狀態", "")
            if "正式分析" in status:
                continue
            if "補查後未升格" in status:
                continue
            ticker = self._extract_ticker(row.get("股票", ""))
            tickers = (ticker,) if ticker else fallback_tickers
            reason = "；".join(
                item
                for item in [
                    f"股票：{row.get('股票', '')}",
                    f"產業位置：{row.get('產業位置', '')}",
                    row.get("狀態", ""),
                    row.get("證據", ""),
                    row.get("排除 / 升格原因", ""),
                    row.get("下一步", ""),
                    f"信心：{row.get('信心', '')}" if row.get("信心") else "",
                ]
                if item
            )
            actions.append(
                FollowUpAction(
                    "ingest_news",
                    f"候選公司未升格，需補齊公司層級證據：{reason}",
                    tickers,
                    priority,
                    "weekly",
                    purpose,
                )
            )
            if needs_company_filing_sources(reason):
                actions.append(
                    FollowUpAction(
                        "ingest_company_filings",
                        f"候選公司公開文件不足，需補官方年報、法說會或 IR 文字來源：{reason}",
                        tickers,
                        priority,
                        "monthly",
                        purpose,
                    )
                )
            weak_or_missing.append(ticker)
        if weak_or_missing:
            actions.append(
                FollowUpAction(
                    "rerun_discovery",
                    "補齊弱證據與待補候選後，重新執行主題拆解與候選升格驗證。",
                    fallback_tickers,
                    priority,
                    "once",
                    purpose,
                )
            )
        return actions

    @classmethod
    def _top_tracking_candidate_rows(cls, rows: list[dict[str, str]], limit: int) -> list[dict[str, str]]:
        candidates = [row for row in rows if "正式分析" not in row.get("狀態", "")]
        return sorted(candidates, key=cls._tracking_candidate_rank)[:limit]

    @staticmethod
    def _tracking_candidate_rank(row: dict[str, str]) -> tuple[int, int, int, str]:
        status = row.get("狀態", "")
        evidence_count, source_count = FollowUpActionPlanner._parse_evidence_counts(row.get("證據", ""))
        confidence = FollowUpActionPlanner._parse_confidence_score(row.get("信心", ""))
        status_rank = 0 if "弱證據" in status else 1
        return (status_rank, -evidence_count, -source_count, -confidence, row.get("股票", ""))

    @staticmethod
    def _parse_evidence_counts(value: str) -> tuple[int, int]:
        numbers = [int(match) for match in re.findall(r"\d+", value)]
        if not numbers:
            return 0, 0
        if len(numbers) == 1:
            return numbers[0], 0
        return numbers[0], numbers[1]

    @staticmethod
    def _parse_confidence_score(value: str) -> int:
        numbers = [int(match) for match in re.findall(r"\d+", value)]
        return numbers[-1] if numbers else 0

    def _actions_from_trigger(self, trigger: str, tickers: tuple[str, ...]) -> list[FollowUpAction]:
        actions: list[FollowUpAction] = []
        if self._has(trigger, "股價歷史", "股價", "成交量", "領先訊號", "近況訊號"):
            actions.append(FollowUpAction("refresh_market", f"監控條件觸發：{trigger}", tickers, "high", "weekly", "tracking"))
        if self._has(trigger, "月營收", "營收"):
            actions.append(FollowUpAction("refresh_monthly_revenue", f"監控條件觸發：{trigger}", tickers, "high", "monthly", "tracking"))
        if self._has(trigger, "估值", "同業", "P/E", "DCF"):
            actions.append(FollowUpAction("refresh_valuations", f"監控條件觸發：{trigger}", tickers, "medium", "weekly", "tracking"))
        if self._has(trigger, "五年財報", "財報", "財務"):
            actions.append(FollowUpAction("refresh_financial_metrics", f"監控條件觸發：{trigger}", tickers, "medium", "monthly", "tracking"))
        if self._has(trigger, "新來源", "公司文本", "AI 歸因", "證據", "來源"):
            actions.append(FollowUpAction("ingest_news", f"監控條件觸發：{trigger}", tickers, "medium", "weekly", "tracking"))
        return actions

    @staticmethod
    def _markdown_table_rows(
        markdown: str,
        heading: str,
        required_headers: tuple[str, ...] = (),
    ) -> list[dict[str, str]]:
        lines = markdown.splitlines()
        try:
            start = lines.index(f"## {heading}")
        except ValueError:
            return []
        table_lines: list[str] = []
        tables: list[list[str]] = []
        for line in lines[start + 1 :]:
            if line.startswith("## "):
                break
            if line.strip().startswith("|"):
                table_lines.append(line.strip())
            elif table_lines:
                tables.append(table_lines)
                table_lines = []
        if table_lines:
            tables.append(table_lines)
        for table_lines in tables:
            rows = FollowUpActionPlanner._parse_markdown_table(table_lines, required_headers)
            if rows:
                return rows
        return []

    @staticmethod
    def _parse_markdown_table(table_lines: list[str], required_headers: tuple[str, ...] = ()) -> list[dict[str, str]]:
        if len(table_lines) < 3:
            return []
        headers = [cell.strip() for cell in table_lines[0].strip("|").split("|")]
        if required_headers and not all(header in headers for header in required_headers):
            return []
        rows = []
        for line in table_lines[2:]:
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) != len(headers):
                continue
            rows.append(dict(zip(headers, cells)))
        return rows

    @staticmethod
    def _extract_ticker(text: str) -> str | None:
        match = re.search(r"\b\d{4}\b", text)
        return match.group(0) if match else None

    @staticmethod
    def _has(text: str, *keywords: str) -> bool:
        return any(keyword in text for keyword in keywords)


def dedupe_actions(actions: list[FollowUpAction]) -> list[FollowUpAction]:
    merged: dict[tuple[str, tuple[str, ...]], FollowUpAction] = {}
    priority_rank = {"low": 0, "medium": 1, "high": 2}
    purpose_rank = {"tracking": 0, "required": 1}
    for action in actions:
        key = action.key()
        existing = merged.get(key)
        if existing is None:
            merged[key] = action
            continue
        priority = action.priority if priority_rank[action.priority] > priority_rank[existing.priority] else existing.priority
        purpose = action.purpose if purpose_rank[action.purpose] > purpose_rank[existing.purpose] else existing.purpose
        reason = existing.reason if existing.reason == action.reason else f"{existing.reason}；{action.reason}"
        merged[key] = FollowUpAction(action.action_type, reason, action.tickers, priority, existing.frequency, purpose)
    return list(merged.values())


def filter_fresh_tracking_actions(actions: list[FollowUpAction], request: ReportRequest) -> list[FollowUpAction]:
    if not actions:
        return []
    filtered, _ = split_fresh_tracking_actions(actions, request)
    return filtered


def skipped_fresh_tracking_actions(actions: list[FollowUpAction], request: ReportRequest) -> list[FollowUpAction]:
    freshness = tracking_freshness_details_by_action(actions, request)
    return [
        action
        for action in actions
        if action.purpose == "tracking"
        and action.action_type != "rerun_analysis"
        and freshness.get(action.key(), {}).get("is_fresh", False)
    ]


def tracking_freshness_by_action(actions: list[FollowUpAction], request: ReportRequest) -> dict[tuple[str, tuple[str, ...]], bool]:
    return {
        key: bool(value.get("is_fresh"))
        for key, value in tracking_freshness_details_by_action(actions, request).items()
    }


def tracking_freshness_details_by_action(actions: list[FollowUpAction], request: ReportRequest) -> dict[tuple[str, tuple[str, ...]], dict]:
    today = today_taipei()
    tracking_actions = [
        action
        for action in actions
        if action.purpose == "tracking" and action.action_type != "rerun_analysis"
    ]
    if not tracking_actions:
        return {}
    tickers = sorted({ticker for action in tracking_actions for ticker in (action.tickers or tuple(request.tickers))})
    if not tickers:
        return {}
    try:
        with session_scope() as session:
            latest_market = {item.ticker: item.trade_date for item in MarketRepository(session).latest_by_tickers(tickers)}
            latest_revenue = {
                item.ticker: item.revenue_date for item in MonthlyRevenueRepository(session).latest_by_tickers(tickers)
            }
            latest_valuation = {
                item.ticker: item.trade_date for item in ValuationMetricRepository(session).latest_by_tickers(tickers)
            }
            latest_company_filing = {}
            for ticker in tickers:
                stats = CompanyFilingRepository(session).stats_by_ticker(ticker)
                if stats.get("latest_date"):
                    latest_company_filing[ticker] = date.fromisoformat(stats["latest_date"])
            metrics = FinancialMetricRepository(session).by_tickers(tickers)
            latest_financial: dict[str, object] = {}
            for metric in metrics:
                current = latest_financial.get(metric.ticker)
                if current is None or metric.report_date > current:
                    latest_financial[metric.ticker] = metric.report_date
    except Exception:
        return {}
    freshness = {}
    thresholds = {
        "refresh_market": (latest_market, TRACKING_FRESHNESS_THRESHOLDS["refresh_market"]),
        "refresh_monthly_revenue": (latest_revenue, TRACKING_FRESHNESS_THRESHOLDS["refresh_monthly_revenue"]),
        "refresh_valuations": (latest_valuation, TRACKING_FRESHNESS_THRESHOLDS["refresh_valuations"]),
        "refresh_financial_metrics": (latest_financial, TRACKING_FRESHNESS_THRESHOLDS["refresh_financial_metrics"]),
        "ingest_company_filings": (latest_company_filing, TRACKING_FRESHNESS_THRESHOLDS["ingest_company_filings"]),
    }
    for action in tracking_actions:
        source = thresholds.get(action.action_type)
        if source is None:
            freshness[action.key()] = {
                "is_fresh": False,
                "max_age_days": None,
                "latest_dates": {},
            }
            continue
        latest_by_ticker, max_age_days = source
        action_tickers = action.tickers or tuple(request.tickers)
        latest_dates = {
            ticker: latest_by_ticker[ticker].isoformat()
            for ticker in action_tickers
            if ticker in latest_by_ticker
        }
        freshness[action.key()] = {
            "is_fresh": bool(action_tickers) and all(
                ticker in latest_by_ticker and latest_by_ticker[ticker] >= today - timedelta(days=max_age_days)
                for ticker in action_tickers
            ),
            "max_age_days": max_age_days,
            "latest_dates": latest_dates,
        }
    return freshness


def skipped_fresh_tracking_details(actions: list[FollowUpAction], request: ReportRequest) -> list[dict]:
    _, rows = split_fresh_tracking_actions(actions, request)
    return rows


def split_fresh_tracking_actions(
    actions: list[FollowUpAction],
    request: ReportRequest,
) -> tuple[list[FollowUpAction], list[dict]]:
    freshness = tracking_freshness_details_by_action(actions, request)
    rows = []
    filtered = []
    for action in actions:
        details = freshness.get(action.key()) or {}
        if action.purpose == "tracking" and action.action_type != "rerun_analysis" and details.get("is_fresh"):
            rows.append({**action.to_dict(), "freshness": details})
            continue
        filtered.append(action)
    has_tracking_work = any(action.purpose == "tracking" and action.action_type != "rerun_analysis" for action in filtered)
    has_required_work = any(action.purpose == "required" and action.action_type != "rerun_analysis" for action in filtered)
    filtered = [
        action
        for action in filtered
        if action.action_type != "rerun_analysis"
        or (action.purpose == "tracking" and has_tracking_work)
        or (action.purpose == "required" and has_required_work)
        or (action.purpose == "required" and "LLM" in action.reason)
    ]
    return filtered, rows


def render_follow_up_actions_markdown(actions: list[FollowUpAction]) -> str:
    if not actions:
        return "目前沒有需要系統自動補強的任務。"
    lines = [
        "系統會把品質缺口與監控條件轉成以下自動補強任務；補強完成後再重新產生報告，避免只把問題列出來卻沒有處理。",
        "",
        "| 任務 | 股票 | 性質 | 優先級 | 頻率 | 觸發原因 |",
        "|---|---|---|---|---|---|",
    ]
    for action in actions:
        tickers = "、".join(action.tickers) if action.tickers else "全主題"
        purpose = "資料缺口補強" if action.purpose == "required" else "追蹤更新"
        lines.append(
            f"| {FOLLOW_UP_ACTION_LABELS.get(action.action_type, action.action_type)} | {tickers} | {purpose} | {action.priority} | "
            f"{action.frequency} | {action.reason} |"
        )
    return "\n".join(lines)


def summarize_follow_up_execution(execution: dict) -> dict:
    results = execution.get("results") or {}
    rows = []
    total_errors = 0
    total_items = 0
    blocked_company_filing_tickers = []
    retryable_company_filing_tickers = []
    rerun_blocker_actions = []
    for key, value in results.items():
        if not isinstance(value, dict):
            rows.append(
                {
                    "task": key,
                    "stored_count": 0,
                    "error_count": 0,
                    "completion": follow_up_completion_status(key, {}),
                }
            )
            continue
        errors = value.get("errors") or []
        error_count = len(errors) if isinstance(errors, list) else 0
        stored_count = _stored_count(value)
        gap_summary = value.get("gap_summary") or {}
        blocked_company_filing_tickers.extend(gap_summary.get("blocked_tickers") or [])
        retryable_company_filing_tickers.extend(gap_summary.get("retryable_tickers") or [])
        rerun_blocker_actions.extend(value.get("next_actions") or [])
        total_errors += error_count
        total_items += stored_count
        rows.append(
            {
                "task": key,
                "stored_count": stored_count,
                "error_count": error_count,
                "source": value.get("source"),
                "target_terms": value.get("target_terms") or [],
                "completion": follow_up_completion_status(key, value),
            }
        )
    unique_blocked = sorted(set(blocked_company_filing_tickers))
    unique_retryable = sorted(set(retryable_company_filing_tickers))
    completion = summarize_follow_up_completion(rows)
    incomplete_tasks = [
        task
        for task in completion["blocked_tasks"]
        if not _nonblocking_partial_candidate_task(task, rows, unique_blocked, total_items)
    ]
    rerun_blockers = []
    if unique_blocked and total_items <= 0:
        rerun_blockers.append(f"公司公開文件仍不足：{', '.join(unique_blocked)}")
    if incomplete_tasks:
        rerun_blockers.append("補強任務未達完成條件：" + "、".join(incomplete_tasks))
        rerun_blocker_actions.extend(follow_up_completion_blocker_actions(rows, incomplete_tasks))
    return {
        "task_result_count": len(rows),
        "stored_count": total_items,
        "error_count": total_errors,
        "has_errors": total_errors > 0,
        "completion": completion,
        "rerun_blocked": bool(rerun_blockers),
        "rerun_blockers": rerun_blockers,
        "rerun_blocker_actions": rerun_blocker_actions,
        "retryable_company_filing_tickers": unique_retryable,
        "items": rows,
}


def _nonblocking_partial_candidate_task(
    task: str,
    rows: list[dict],
    blocked_company_filing_tickers: list[str],
    total_items: int,
) -> bool:
    row = next((item for item in rows if item.get("task") == task), {})
    if task.startswith("ingest_news"):
        is_candidate_guard = row.get("source") == "follow-up action guard"
        completion = row.get("completion") or {}
        observed = completion.get("observed") or {}
        matched_target_count = int(observed.get("matched_target_count") or 0)
        return (bool(row.get("target_terms")) or is_candidate_guard) and total_items > 0 and (
            matched_target_count > 0
            or int(row.get("error_count") or 0) > 0
        )
    if task.startswith("ingest_company_filings") and blocked_company_filing_tickers and total_items <= 0:
        return True
    if task.startswith("ingest_company_filings") and blocked_company_filing_tickers and total_items > 0:
        return True
    if task.startswith("ingest_company_filings") and total_items > 0:
        is_candidate_guard = row.get("source") == "follow-up action guard"
        return (bool(row.get("target_terms")) or is_candidate_guard) and (
            int(row.get("error_count") or 0) > 0
        )
    return False


def follow_up_completion_blocker_actions(rows: list[dict], incomplete_tasks: list[str]) -> list[dict]:
    row_by_task = {row.get("task"): row for row in rows}
    actions = []
    for task in incomplete_tasks:
        row = row_by_task.get(task) or {}
        completion = row.get("completion") or {}
        action_type, _, ticker_text = task.partition(":")
        actions.append(
            {
                "ticker": ticker_text or "",
                "company_name": "",
                "action": "complete_follow_up_check",
                "task": task,
                "check": completion.get("check") or "manual_review",
                "target": follow_up_completion_target_label(action_type),
                "reason": follow_up_completion_reason(task, completion),
                "observed": completion.get("observed") or {},
                "required": completion.get("required") or {},
            }
        )
    return actions


def follow_up_completion_target_label(action_type: str) -> str:
    labels = {
        "ingest_news": "新聞/研究/產業證據",
        "ingest_company_filings": "公司公開文件",
        "refresh_market": "股價與量能",
        "refresh_monthly_revenue": "月營收",
        "refresh_financial_metrics": "五年財務資料",
        "refresh_valuations": "估值資料",
        "rerun_discovery": "AI 主題拆解與候選白名單",
    }
    return labels.get(action_type, action_type)


def follow_up_completion_reason(task: str, completion: dict) -> str:
    observed = completion.get("observed") or {}
    required = completion.get("required") or {}
    return f"{task} 未達完成條件；目前 {observed}，要求 {required}。"


def summarize_follow_up_completion(rows: list[dict]) -> dict:
    completed = sum(1 for row in rows if (row.get("completion") or {}).get("completed"))
    blocked = [
        row["task"]
        for row in rows
        if not (row.get("completion") or {}).get("completed")
    ]
    return {
        "completed_count": completed,
        "total_count": len(rows),
        "all_completed": bool(rows) and completed == len(rows),
        "blocked_tasks": blocked,
    }


def follow_up_completion_status(task: str, result: dict) -> dict:
    action_type = task.split(":", 1)[0]
    stored_count = _stored_count(result)
    errors = result.get("errors") or []
    error_count = len(errors) if isinstance(errors, list) else 0
    if action_type == "ingest_company_filings":
        blocked = ((result.get("gap_summary") or {}).get("blocked_tickers") or [])
        return {
            "check": "company_filing_quality",
            "completed": stored_count > 0 and not blocked,
            "observed": {"stored_count": stored_count, "blocked_tickers": blocked},
            "required": {"min_documents": 1, "blocked_tickers": []},
        }
    if action_type == "refresh_market":
        return {
            "check": "market_history_coverage",
            "completed": stored_count >= 120 and error_count == 0,
            "observed": {"stored_count": stored_count, "error_count": error_count},
            "required": {"min_days": 120, "error_count": 0},
        }
    if action_type == "refresh_monthly_revenue":
        return {
            "check": "monthly_revenue_coverage",
            "completed": stored_count >= 12 and error_count == 0,
            "observed": {"stored_count": stored_count, "error_count": error_count},
            "required": {"min_months": 12, "error_count": 0},
        }
    if action_type == "refresh_financial_metrics":
        return {
            "check": "financial_metric_coverage",
            "completed": stored_count >= 5 and error_count == 0,
            "observed": {"stored_count": stored_count, "error_count": error_count},
            "required": {"min_years": 5, "error_count": 0},
        }
    if action_type == "refresh_valuations":
        return {
            "check": "valuation_availability",
            "completed": stored_count > 0 and error_count == 0,
            "observed": {"stored_count": stored_count, "error_count": error_count},
            "required": {"min_records": 1, "error_count": 0},
        }
    if action_type == "ingest_news":
        target_tickers = [ticker for ticker in task.split(":", 1)[1].split(",") if ticker] if ":" in task else []
        matched_count = _matched_target_item_count(
            result.get("items") or [],
            target_tickers,
            result.get("target_terms") or [],
        )
        coverage_fallback_count = int(result.get("coverage_fallback_count") or 0)
        completed = stored_count > 0 and matched_count > 0
        if not target_tickers and coverage_fallback_count > 0:
            completed = stored_count > 0
        return {
            "check": "company_evidence_sources",
            "completed": completed,
            "observed": {
                "stored_count": stored_count,
                "matched_target_count": matched_count,
                "coverage_fallback_count": coverage_fallback_count,
                "error_count": error_count,
            },
            "required": {"min_documents": 1, "min_matched_target_documents": 1},
        }
    if action_type == "rerun_discovery":
        status = result.get("status")
        return {
            "check": "candidate_revalidation_ready",
            "completed": status in {"planned", "completed", "ready"},
            "observed": {"status": status},
            "required": {"status": "planned_or_ready"},
        }
    return {
        "check": "manual_review",
        "completed": stored_count > 0 and error_count == 0,
        "observed": {"stored_count": stored_count, "error_count": error_count},
        "required": {"manual_review": True},
    }


def _stored_count(result: dict) -> int:
    for key in ("stored_history_count", "stored_count", "count"):
        value = result.get(key)
        if isinstance(value, int):
            return value
    stored = result.get("stored")
    if isinstance(stored, list):
        return len(stored)
    latest = result.get("latest")
    if isinstance(latest, list):
        return len(latest)
    return 0


def _matched_target_item_count(items: list, target_tickers: list[str], target_terms: list[str] | None = None) -> int:
    if not target_tickers and not target_terms:
        return len(items)
    targets = set(target_tickers)
    text_terms = [
        term.lower()
        for term in [*target_tickers, *(target_terms or [])]
        if term
    ]
    matched = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        matches = item.get("entity_matches") or []
        if any(isinstance(match, dict) and match.get("ticker") in targets for match in matches):
            matched += 1
            continue
        haystack = " ".join(
            str(item.get(key) or "")
            for key in ["title", "publisher", "url", "id", "excerpt", "text"]
        ).lower()
        if haystack and any(term in haystack for term in text_terms):
            matched += 1
    return matched


async def execute_follow_up_actions(
    actions: list[FollowUpAction],
    request: ReportRequest,
    news_limit: int = 30,
) -> dict:
    today = today_taipei()
    result: dict[str, object] = {"actions": [action.to_dict() for action in actions], "results": {}}
    executable = [action for action in actions if action.action_type != "rerun_analysis"]
    semaphore = asyncio.Semaphore(FOLLOW_UP_ACTION_CONCURRENCY)

    async def run_action(action: FollowUpAction) -> tuple[str, dict]:
        result_key = follow_up_result_key(action, request)
        tickers = list(action.tickers)
        try:
            async with semaphore:
                action_result = await asyncio.wait_for(
                    execute_single_follow_up_action(action, request, news_limit, today),
                    timeout=FOLLOW_UP_ACTION_TIMEOUT_SECONDS,
                )
        except asyncio.TimeoutError:
            action_result = follow_up_action_error_result(
                action,
                tickers,
                f"補強任務超過 {FOLLOW_UP_ACTION_TIMEOUT_SECONDS} 秒，已先記錄為可重試缺口。",
                "timeout",
            )
        except Exception as exc:
            action_result = follow_up_action_error_result(
                action,
                tickers,
                str(exc) or exc.__class__.__name__,
                "execution_error",
            )
        return result_key, action_result

    for result_key, action_result in await asyncio.gather(*(run_action(action) for action in executable)):
        result["results"][result_key] = action_result
    result["execution_summary"] = summarize_follow_up_execution(result)
    return result


def execute_follow_up_actions_sync(actions: list[FollowUpAction], request: ReportRequest, news_limit: int = 30) -> dict:
    return asyncio.run(execute_follow_up_actions(actions, request, news_limit))


async def execute_single_follow_up_action(
    action: FollowUpAction,
    request: ReportRequest,
    news_limit: int,
    today,
) -> dict:
    pipeline = IngestionPipeline()
    tickers = list(action.tickers or tuple(request.tickers))
    if action.action_type == "ingest_news":
        return await ingest_follow_up_news(
            pipeline,
            action,
            request,
            news_limit,
            today,
        )
    if action.action_type == "ingest_company_filings":
        document_types = company_filing_document_types_from_reason(action.reason)
        company_name = company_name_from_follow_up_reason(action.reason)
        company_names = {ticker: company_name for ticker in tickers if company_name}
        result = await pipeline.ingest_company_filings(
            tickers,
            limit_per_query=max(2, min(5, news_limit // 10)),
            filter_allowed=False,
            document_types=document_types,
            company_names=company_names,
        )
        result["target_terms"] = follow_up_target_terms(action)
        return result
    if action.action_type == "refresh_market":
        return await pipeline.refresh_market(
            tickers,
            today - timedelta(days=max(request.lookback_days, 240)),
            today,
            filter_allowed=False,
        )
    if action.action_type == "refresh_monthly_revenue":
        return await pipeline.refresh_monthly_revenue(
            tickers,
            today - timedelta(days=450),
            today,
            filter_allowed=False,
        )
    if action.action_type == "refresh_financial_metrics":
        return await pipeline.refresh_financial_metrics(
            tickers,
            today - timedelta(days=365 * 6),
            today,
            filter_allowed=False,
        )
    if action.action_type == "refresh_valuations":
        return await pipeline.refresh_valuations(
            tickers,
            today - timedelta(days=max(request.lookback_days, 30)),
            today,
            filter_allowed=False,
        )
    if action.action_type == "rerun_discovery":
        return {
            "status": "planned",
            "reason": "主題拆解重跑會在補強後重新產生報告時執行。",
        }
    return follow_up_action_error_result(action, tickers, f"未知補強任務：{action.action_type}", "unknown_action")


def follow_up_result_key(action: FollowUpAction, request: ReportRequest) -> str:
    tickers = list(action.tickers)
    return action.action_type if not tickers else f"{action.action_type}:{','.join(tickers)}"


def follow_up_action_error_result(
    action: FollowUpAction,
    tickers: list[str],
    message: str,
    category: str,
) -> dict:
    return {
        "count": 0,
        "items": [],
        "target_terms": follow_up_target_terms(action),
        "errors": [
            {
                "action_type": action.action_type,
                "tickers": tickers,
                "error": message,
                "category": category,
            }
        ],
        "source": "follow-up action guard",
    }


def company_filing_document_types_from_reason(reason: str) -> list[str] | None:
    document_types = []
    if "annual_report" in reason or "年報" in reason:
        document_types.append("annual_report")
    if "investor_presentation" in reason or "法說" in reason or "法人說明" in reason:
        document_types.append("investor_presentation")
    if "prospectus" in reason or "公開說明書" in reason:
        document_types.append("prospectus")
    if "material_information" in reason or "重大訊息" in reason:
        document_types.append("material_information")
    return list(dict.fromkeys(document_types)) or None


def needs_company_filing_sources(reason: str) -> bool:
    return any(keyword in reason for keyword in ["年報", "法說", "法人說明", "IR", "公開文件"])


async def ingest_follow_up_news(
    pipeline: IngestionPipeline,
    action: FollowUpAction,
    request: ReportRequest,
    news_limit: int,
    today,
) -> dict:
    start_date = today - timedelta(days=max(request.lookback_days, 30))
    queries = follow_up_news_queries(action, request)
    if not queries:
        return await pipeline.ingest_feeds(
            enabled_sources_only=True,
            topic=request.topic,
            limit=news_limit,
            start_date=start_date,
            end_date=today,
        )

    per_query_limit = max(3, min(10, news_limit // max(1, len(queries))))
    results = []
    items = []
    errors = []
    target_terms = follow_up_target_terms(action)
    target_tickers = list(action.tickers)
    cached_items = cached_follow_up_news_items(pipeline, target_tickers, target_terms, news_limit)
    if _has_follow_up_target_match(cached_items, target_tickers, target_terms):
        return {
            "count": len(cached_items),
            "items": cached_items,
            "errors": [],
            "suppressed_errors": [],
            "queries": [],
            "web_search": None,
            "fallback": None,
            "target_terms": target_terms,
            "source": "cached follow-up news evidence",
        }
    semaphore = asyncio.Semaphore(4)

    async def fetch_query(query: str) -> tuple[dict, dict]:
        url = google_news_rss_url(query)
        try:
            async with semaphore:
                result = await asyncio.wait_for(
                    pipeline.ingest_feeds(
                        url=url,
                        publisher="Google News follow-up",
                        limit=per_query_limit,
                        enabled_sources_only=False,
                        start_date=start_date,
                        end_date=today,
                    ),
                    timeout=FOLLOW_UP_NEWS_QUERY_TIMEOUT_SECONDS,
                )
        except Exception as exc:
            result = {
                "count": 0,
                "items": [],
                "errors": [{"source": url, "error": str(exc) or exc.__class__.__name__}],
            }
        return result, {
            "query": query,
            "url": url,
            "count": result.get("count", 0),
            "errors": result.get("errors", []),
        }

    for result, query_result in await asyncio.gather(*(fetch_query(query) for query in queries)):
        results.append(query_result)
        items.extend(result.get("items", []) or [])
        errors.extend(result.get("errors", []) or [])
    deduped_items = filter_follow_up_target_items(
        dedupe_follow_up_items(items),
        target_tickers,
        target_terms,
    )
    fallback = None
    coverage_fallback_count = 0
    suppressed_errors = []
    if coverage_fallback_count <= 0 and not _has_follow_up_target_match(deduped_items, target_tickers, target_terms):
        google_errors = list(errors)
        fallback_topic = follow_up_fallback_topic(action, request)
        try:
            fallback = await asyncio.wait_for(
                pipeline.ingest_feeds(
                    enabled_sources_only=True,
                    topic=fallback_topic,
                    limit=news_limit,
                    start_date=start_date,
                    end_date=today,
                ),
                timeout=FOLLOW_UP_NEWS_FALLBACK_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            fallback = {
                "count": 0,
                "items": [],
                "errors": [{"source": fallback_topic, "error": str(exc) or exc.__class__.__name__}],
            }
        items.extend(fallback.get("items", []) or [])
        fallback_errors = fallback.get("errors", []) or []
        errors = fallback_errors if fallback.get("items") else [*google_errors, *fallback_errors]
        suppressed_errors = google_errors if fallback.get("items") else []
        deduped_items = filter_follow_up_target_items(
            dedupe_follow_up_items(items),
            target_tickers,
            target_terms,
        )
        if not target_tickers and not deduped_items and fallback.get("items"):
            fallback_items = dedupe_follow_up_items(fallback.get("items") or [])
            coverage_fallback_count = len(fallback_items)
            deduped_items = fallback_items[:news_limit]
    web_search = None
    if coverage_fallback_count <= 0 and not _has_follow_up_target_match(deduped_items, target_tickers, target_terms):
        prior_errors = list(errors)
        try:
            web_search = await asyncio.wait_for(
                pipeline.ingest_web_search(
                    queries=queries,
                    topic=follow_up_fallback_topic(action, request),
                    limit_per_query=max(2, min(5, news_limit // max(1, len(queries)))),
                    start_date=start_date,
                    end_date=today,
                    target_terms=target_terms,
                ),
                timeout=FOLLOW_UP_NEWS_WEB_SEARCH_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            web_search = {
                "count": 0,
                "items": [],
                "errors": [{"source": "targeted web search", "error": str(exc) or exc.__class__.__name__}],
                "queries": [],
                "target_terms": target_terms,
            }
        items.extend(web_search.get("items", []) or [])
        web_errors = web_search.get("errors", []) or []
        if web_search.get("items"):
            suppressed_errors.extend(prior_errors)
            errors = web_errors
        else:
            errors.extend(web_errors)
        deduped_items = filter_follow_up_target_items(
            dedupe_follow_up_items(items),
            target_tickers,
            target_terms,
        )
    source_parts = ["Google News targeted follow-up"]
    if fallback:
        source_parts.append("enabled-source fallback")
    if web_search:
        source_parts.append("targeted web search")
    return {
        "count": len(deduped_items),
        "items": deduped_items,
        "errors": errors,
        "suppressed_errors": suppressed_errors,
        "queries": results,
        "web_search": web_search,
        "fallback": fallback,
        "coverage_fallback_count": coverage_fallback_count,
        "target_terms": target_terms,
        "source": " + ".join(source_parts),
    }


def cached_follow_up_news_items(
    pipeline: IngestionPipeline,
    target_tickers: list[str],
    target_terms: list[str],
    limit: int,
) -> list[dict]:
    mapper = getattr(pipeline, "mapper", None)
    if mapper is None:
        return []
    queries = dedupe_terms([*target_tickers, *target_terms], limit=8)
    if not queries:
        return []
    try:
        with session_scope() as session:
            repository = NewsRepository(session)
            filing_repository = CompanyFilingRepository(session)
            documents = []
            for query in queries:
                documents.extend(repository.search_documents(query, limit=max(5, limit)))
                filing_documents = filing_repository.search_documents(
                    query,
                    tickers=target_tickers or None,
                    limit=max(5, limit),
                )
                documents.extend(
                    CompanyFilingRepository.to_news_document(document)
                    for document in filing_documents
                )
    except Exception:
        return []
    deduped_documents = IngestionPipeline._dedupe_documents(documents)
    items = []
    for document in deduped_documents[: max(5, limit * 2)]:
        matches = mapper.match_document(document)
        items.append(
            {
                "id": document.id,
                "title": document.title,
                "publisher": document.source.publisher,
                "published_at": document.source.published_at.isoformat()
                if document.source.published_at
                else None,
                "url": document.source.url,
                "excerpt": document.text[:500],
                "entity_matches": [match.model_dump(mode="json") for match in matches],
            }
        )
    return filter_follow_up_target_items(items, target_tickers, target_terms)[:limit]


def dedupe_follow_up_items(items: list) -> list[dict]:
    return list(
        {
            item.get("id") or item.get("url") or item.get("title"): item
            for item in items
            if isinstance(item, dict)
        }.values()
    )


def filter_follow_up_target_items(
    items: list[dict],
    target_tickers: list[str],
    target_terms: list[str],
) -> list[dict]:
    if not target_tickers and not target_terms:
        return items
    return [
        item
        for item in items
        if _matched_target_item_count([item], target_tickers, target_terms) > 0
    ]


def follow_up_target_terms(action: FollowUpAction) -> list[str]:
    terms = [*list(action.tickers), company_name_from_follow_up_reason(action.reason)]
    terms.extend(follow_up_query_terms(action.reason)[:3])
    return dedupe_terms(terms, limit=8)


def follow_up_news_queries(action: FollowUpAction, request: ReportRequest) -> list[str]:
    tickers = list(action.tickers)
    company_name = company_name_from_follow_up_reason(action.reason)
    context_terms = follow_up_query_terms(action.reason)
    context = " ".join(context_terms[:4])
    queries = []
    for ticker in tickers:
        if ticker:
            ticker_context = " ".join(part for part in [ticker, company_name, request.topic, context] if part)
            queries.append(ticker_context.strip())
            queries.append(f"{ticker} 台股 {request.topic} 供應鏈 證據".strip())
            queries.append(" ".join(part for part in [ticker, company_name, context, "公司公告 法說會"] if part))
            queries.append(" ".join(part for part in [ticker, company_name, context, "site:mops.twse.com.tw"] if part))
            if needs_company_filing_sources(action.reason):
                queries.append(" ".join(part for part in [ticker, company_name, "年報 法說會 IR"] if part))
            if needs_confidence_sources(action.reason):
                queries.append(f"{ticker} {request.topic} 法說會 近期 來源 日期".strip())
                queries.append(f"{ticker} {request.topic} monthly revenue investor conference".strip())
    for term in context_terms[:4]:
        queries.append(f"{request.topic} {term}".strip())
    if context_terms and needs_confidence_sources(action.reason):
        queries.append(f"{request.topic} 近期 公司來源 發布日期 多來源".strip())
    return dedupe_queries(queries, limit=8)


def _has_follow_up_target_match(items: list[dict], target_tickers: list[str], target_terms: list[str]) -> bool:
    if not items:
        return False
    if not target_tickers and not target_terms:
        return True
    return _matched_target_item_count(items, target_tickers, target_terms) > 0


def company_name_from_follow_up_reason(reason: str) -> str:
    match = re.search(r"股票：\d+\s+([^；]+)", reason)
    return match.group(1).strip() if match else ""


def follow_up_fallback_topic(action: FollowUpAction, request: ReportRequest) -> str:
    parts = [request.topic, *list(action.tickers), company_name_from_follow_up_reason(action.reason)]
    parts.extend(follow_up_query_terms(action.reason)[:3])
    return " ".join(part for part in parts if part).strip() or request.topic


def follow_up_query_terms(reason: str) -> list[str]:
    terms = []
    segment = re.search(r"產業位置：([^；]+)", reason)
    if segment:
        terms.append(segment.group(1).strip())
    source_gap = re.search(r"(?:缺少來源覆蓋子題|缺少的資料意圖|資料意圖)：([^；]+)", reason)
    if source_gap:
        for part in re.split(r"[、,，]", source_gap.group(1)):
            if part.strip():
                terms.append(part.strip())
            for subpart in re.split(r"與|和", part):
                if subpart.strip() and subpart.strip() != part.strip():
                    terms.append(subpart.strip())
    for keyword in [
        "協作機器人",
        "人形機器人",
        "減速器",
        "伺服馬達",
        "滾珠螺桿",
        "線性滑軌",
        "法說會",
        "月營收",
        "毛利率",
        "估值",
        "資本支出",
    ]:
        if keyword in reason:
            terms.append(keyword)
    if not terms:
        terms.extend(compact_query_text(reason).split()[:4])
    return dedupe_terms(terms, limit=6)


def dedupe_terms(terms: list[str], limit: int) -> list[str]:
    deduped = []
    seen = set()
    for term in terms:
        normalized = re.sub(r"\s+", " ", term).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
        if len(deduped) >= limit:
            break
    return deduped


def needs_confidence_sources(reason: str) -> bool:
    return any(
        keyword in reason
        for keyword in [
            "證據信心",
            "信心：",
            "有日期",
            "近期",
            "不同發布者",
            "日期來源",
        ]
    )


def compact_query_text(text: str) -> str:
    cleaned = re.sub(r"[|:：；,，。/]+", " ", text)
    terms = [
        term
        for term in cleaned.split()
        if term
        and term not in {"候選公司未升格", "需補齊公司層級證據", "股票", "產業位置", "下一步"}
    ]
    return " ".join(terms[:12])


def dedupe_queries(queries: list[str], limit: int) -> list[str]:
    deduped = []
    seen = set()
    for query in queries:
        normalized = re.sub(r"\s+", " ", query).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
        if len(deduped) >= limit:
            break
    return deduped


def google_news_rss_url(query: str) -> str:
    return (
        "https://news.google.com/rss/search?"
        f"q={quote_plus(query)}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    )
