from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import timedelta

from app.core.async_bridge import run_async_from_sync
from app.core.time import today_taipei
from app.db.session import session_scope
from app.models.schemas import ReportRequest
from app.services import followup_freshness as _followup_freshness
from app.services.followup_completion import (
    follow_up_completion_blocker_actions as follow_up_completion_blocker_actions,
    follow_up_completion_reason as follow_up_completion_reason,
    follow_up_completion_status as follow_up_completion_status,
    follow_up_completion_target_label as follow_up_completion_target_label,
    summarize_follow_up_completion as summarize_follow_up_completion,
    summarize_follow_up_execution as summarize_follow_up_execution,
)
from app.services.followup_evidence import (
    company_filing_document_types_from_reason as company_filing_document_types_from_reason,
    company_name_from_follow_up_reason as company_name_from_follow_up_reason,
    follow_up_news_queries as follow_up_news_queries,
    follow_up_target_terms as follow_up_target_terms,
    ingest_follow_up_news as ingest_follow_up_news,
    needs_company_filing_sources as needs_company_filing_sources,
)
from app.services.followup_freshness import TRACKING_FRESHNESS_THRESHOLDS as TRACKING_FRESHNESS_THRESHOLDS
from app.services.ingestion import IngestionPipeline


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
TRACKING_CANDIDATE_LIMIT = 5
FOLLOW_UP_ACTION_CONCURRENCY = 4
FOLLOW_UP_ACTION_TIMEOUT_SECONDS = 90


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


def manual_tracking_follow_up_actions(request: ReportRequest) -> list[FollowUpAction]:
    tickers = tuple(request.tickers)
    return [
        FollowUpAction(
            "ingest_news",
            "使用者手動要求補抓資料，刷新主題與公司層級證據。",
            tickers,
            "medium",
            "once",
            "tracking",
        ),
        FollowUpAction(
            "rerun_analysis",
            "手動補抓資料後重跑分析，確認投資結論是否需要調整。",
            tickers,
            "high",
            "once",
            "tracking",
        ),
    ]


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
        actions: list[FollowUpAction] = []
        metrics = quality_gate.get("metrics") or {}
        if int(metrics.get("market_stale_count") or 0) > 0:
            actions.append(
                FollowUpAction("refresh_market", "快取救援資料：刷新股價歷史、成交量與近況訊號。", tickers, "high", "weekly")
            )
        if int(metrics.get("monthly_revenue_stale_count") or 0) > 0:
            actions.append(
                FollowUpAction("refresh_monthly_revenue", "快取救援資料：刷新月營收與成長加速資料。", tickers, "high", "monthly")
            )
        if int(metrics.get("financial_metrics_stale_ticker_count") or 0) > 0:
            actions.append(
                FollowUpAction("refresh_financial_metrics", "快取救援資料：刷新近五年財務資料。", tickers, "high", "monthly")
            )
        if int(metrics.get("valuation_stale_count") or 0) > 0:
            actions.append(
                FollowUpAction("refresh_valuations", "快取救援資料：刷新估值與同業比較資料。", tickers, "high", "weekly")
            )
        issue_text = "；".join(
            [
                *[str(item) for item in quality_gate.get("blockers") or []],
                *[str(item) for item in quality_gate.get("warnings") or []],
                *[str(item) for item in quality_gate.get("remediation_actions") or []],
            ]
        )
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
                    f"信心：{self._candidate_confidence_field(row)}" if self._candidate_confidence_field(row) else "",
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
        confidence = FollowUpActionPlanner._parse_confidence_score(
            FollowUpActionPlanner._candidate_confidence_field(row)
        )
        status_rank = 0 if "弱證據" in status else 1
        return (status_rank, -evidence_count, -source_count, -confidence, row.get("股票", ""))

    @staticmethod
    def _candidate_confidence_field(row: dict[str, str]) -> str:
        return row.get("入選支持度") or row.get("入選證據信心") or row.get("信心", "")

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
    return _followup_freshness.filter_fresh_tracking_actions(
        actions,
        request,
        split_func=split_fresh_tracking_actions,
    )


def skipped_fresh_tracking_actions(actions: list[FollowUpAction], request: ReportRequest) -> list[FollowUpAction]:
    return _followup_freshness.skipped_fresh_tracking_actions(
        actions,
        request,
        freshness_details_func=tracking_freshness_details_by_action,
    )


def tracking_freshness_by_action(actions: list[FollowUpAction], request: ReportRequest) -> dict[tuple[str, tuple[str, ...]], bool]:
    return _followup_freshness.tracking_freshness_by_action(
        actions,
        request,
        freshness_details_func=tracking_freshness_details_by_action,
    )


def tracking_freshness_details_by_action(actions: list[FollowUpAction], request: ReportRequest) -> dict[tuple[str, tuple[str, ...]], dict]:
    return _followup_freshness.tracking_freshness_details_by_action(
        actions,
        request,
        session_scope_func=session_scope,
        today_func=today_taipei,
        thresholds=TRACKING_FRESHNESS_THRESHOLDS,
    )


def skipped_fresh_tracking_details(actions: list[FollowUpAction], request: ReportRequest) -> list[dict]:
    _, rows = split_fresh_tracking_actions(actions, request)
    return rows


def split_fresh_tracking_actions(
    actions: list[FollowUpAction],
    request: ReportRequest,
) -> tuple[list[FollowUpAction], list[dict]]:
    return _followup_freshness.split_fresh_tracking_actions(
        actions,
        request,
        freshness_details_func=tracking_freshness_details_by_action,
    )


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
    return run_async_from_sync(
        execute_follow_up_actions(actions, request, news_limit),
        operation="follow_up.execute_actions",
    )


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
