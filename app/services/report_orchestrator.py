from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field


class RecoveryAction(BaseModel):
    action_type: str
    reason: str
    tickers: list[str] = Field(default_factory=list)
    priority: str = "medium"
    tool: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)


class QualityRecoveryPlan(BaseModel):
    mode: str = "agentic_rag_recovery"
    status: str
    triggers: list[str] = Field(default_factory=list)
    actions: list[RecoveryAction] = Field(default_factory=list)


class QualityRecoveryOrchestrator:
    """Plans recovery tool calls when a report quality gate exposes recoverable data gaps."""

    def plan(
        self,
        *,
        blockers: list[str],
        warnings: list[str],
        metrics: dict[str, Any],
        promoted_tickers: list[str],
    ) -> QualityRecoveryPlan:
        issue_text = "；".join([*blockers, *warnings])
        actions: list[RecoveryAction] = []
        triggers: list[str] = []
        tickers = [str(ticker) for ticker in promoted_tickers if str(ticker)]
        promoted_count = int(metrics.get("promoted_count") or len(tickers))

        source_count = int(metrics.get("dynamic_source_count") or 0)
        if source_count < 12 or any(term in issue_text for term in ["來源入庫篇數過少", "資料來源偏少", "發布者過於單一"]):
            triggers.append("source_coverage_gap")
            actions.append(
                RecoveryAction(
                    action_type="ingest_news",
                    reason="來源不足或發布者過於單一，先補抓多來源新聞、研究與產業證據。",
                    tickers=tickers,
                    priority="high",
                    tool="news_search",
                    parameters={
                        "min_sources": 12,
                        "lookback_days": int(metrics.get("source_lookback_days") or 90),
                    },
                )
            )

        if int(metrics.get("missing_subtopic_count") or 0) or int(metrics.get("weak_subtopic_count") or 0):
            triggers.append("subtopic_retrieval_gap")
            actions.append(
                RecoveryAction(
                    action_type="ingest_news",
                    reason="主題拆解仍有缺來源或弱來源子題，針對子題補抓資料後重驗證。",
                    tickers=tickers,
                    priority="high",
                    tool="rag_search",
                    parameters={"focus": "missing_or_weak_subtopics", "min_sources_per_subtopic": 2},
                )
            )

        if promoted_count and (
            float(metrics.get("market_coverage") or 0) < 1
            or int(metrics.get("market_stale_count") or 0)
            or int(metrics.get("market_latest_only_count") or 0)
            or int(metrics.get("market_older_than_database_latest_count") or 0)
            or (
                metrics.get("market_latest_trade_date_coverage") is not None
                and float(metrics.get("market_latest_trade_date_coverage") or 0) < 0.8
            )
        ):
            triggers.append("market_data_gap")
            actions.append(
                RecoveryAction(
                    action_type="refresh_market",
                    reason="股價、量能或交易日覆蓋不足，刷新市場資料後再計算近況訊號。",
                    tickers=tickers,
                    priority="high",
                    tool="market_refresh",
                    parameters={"history_days": 120},
                )
            )

        if promoted_count and (
            float(metrics.get("monthly_revenue_coverage") or 0) < 1
            or int(metrics.get("monthly_revenue_stale_count") or 0)
            or int(metrics.get("monthly_revenue_latest_only_count") or 0)
        ):
            triggers.append("monthly_revenue_gap")
            actions.append(
                RecoveryAction(
                    action_type="refresh_monthly_revenue",
                    reason="月營收覆蓋不足或含快取救援，補齊近 12 個月以上資料。",
                    tickers=tickers,
                    priority="high",
                    tool="monthly_revenue_refresh",
                    parameters={"history_months": 18},
                )
            )

        if promoted_count and (
            int(metrics.get("financial_metrics_count") or 0) < promoted_count * 8
            or int(metrics.get("financial_metrics_stale_ticker_count") or 0)
            or int(metrics.get("financial_metrics_latest_only_ticker_count") or 0)
        ):
            triggers.append("financial_metrics_gap")
            actions.append(
                RecoveryAction(
                    action_type="refresh_financial_metrics",
                    reason="五年財務資料不足或含救援資料，補齊多年財報指標。",
                    tickers=tickers,
                    priority="medium",
                    tool="financial_metrics_refresh",
                    parameters={"history_years": 6},
                )
            )

        if promoted_count and (
            float(metrics.get("valuation_coverage") or 0) < 1
            or int(metrics.get("valuation_stale_count") or 0)
            or int(metrics.get("valuation_latest_only_count") or 0)
        ):
            triggers.append("valuation_gap")
            actions.append(
                RecoveryAction(
                    action_type="refresh_valuations",
                    reason="估值覆蓋不足或含救援資料，刷新 P/E、P/B 與殖利率。",
                    tickers=tickers,
                    priority="medium",
                    tool="valuation_refresh",
                    parameters={"latest": True},
                )
            )

        company_filing_coverage = metrics.get("company_filing_coverage")
        if promoted_count and company_filing_coverage is not None and float(company_filing_coverage or 0) < 1:
            triggers.append("company_filing_gap")
            actions.append(
                RecoveryAction(
                    action_type="ingest_company_filings",
                    reason="公司公開文件不足，補抓年報、法說會或官方 IR 文件。",
                    tickers=tickers,
                    priority="medium",
                    tool="company_filing_search",
                    parameters={"limit_per_ticker": 2},
                )
            )

        actions = _dedupe_actions(actions)
        if actions:
            actions.append(
                RecoveryAction(
                    action_type="rerun_analysis",
                    reason="補資料後重新產生報告，並要求品質門檻無 blocker 才輸出最終結論。",
                    tickers=tickers,
                    priority="high",
                    tool="report_build",
                    parameters={"depends_on": [action.action_type for action in actions]},
                )
            )
        return QualityRecoveryPlan(
            status="planned" if actions else "not_needed",
            triggers=sorted(set(triggers)),
            actions=actions,
        )

    async def execute(
        self,
        plan: QualityRecoveryPlan,
        tools: dict[str, Callable[[RecoveryAction], Any]],
    ) -> dict[str, Any]:
        results: dict[str, Any] = {}
        for action in plan.actions:
            tool = tools.get(action.action_type) or tools.get(action.tool)
            if tool is None:
                results[action.action_type] = {"status": "skipped", "reason": "tool_not_registered"}
                continue
            result = tool(action)
            if hasattr(result, "__await__"):
                result = await result
            results[action.action_type] = {"status": "completed", "result": result}
        return results


def build_quality_recovery_plan(
    *,
    blockers: list[str],
    warnings: list[str],
    metrics: dict[str, Any],
    promoted_tickers: list[str],
) -> dict[str, Any]:
    return QualityRecoveryOrchestrator().plan(
        blockers=blockers,
        warnings=warnings,
        metrics=metrics,
        promoted_tickers=promoted_tickers,
    ).model_dump()


def _dedupe_actions(actions: list[RecoveryAction]) -> list[RecoveryAction]:
    deduped: list[RecoveryAction] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for action in actions:
        key = (action.action_type, tuple(action.tickers))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(action)
    return deduped
