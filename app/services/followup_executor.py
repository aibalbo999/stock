from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any, Protocol

from app.core.time import today_taipei
from app.models.schemas import ReportRequest
from app.services.followup_completion import summarize_follow_up_execution
from app.services.followup_evidence import (
    company_filing_document_types_from_reason,
    company_name_from_follow_up_reason,
    follow_up_target_terms,
    ingest_follow_up_news,
)
from app.services.ingestion import IngestionPipeline


FOLLOW_UP_ACTION_CONCURRENCY = 4
FOLLOW_UP_ACTION_TIMEOUT_SECONDS = 90


class FollowUpExecutorAction(Protocol):
    action_type: str
    reason: str
    tickers: tuple[str, ...]

    def to_dict(self) -> dict: ...


PipelineFactory = Callable[[], IngestionPipeline]
TodayProvider = Callable[[], date]
ExecutionSummaryFunc = Callable[[dict], dict]
SingleActionExecutor = Callable[[FollowUpExecutorAction, ReportRequest, int, date], Any]
ErrorResultFunc = Callable[[FollowUpExecutorAction, list[str], str, str], dict]


async def execute_follow_up_actions(
    actions: list[FollowUpExecutorAction],
    request: ReportRequest,
    news_limit: int = 30,
    *,
    pipeline_factory: PipelineFactory = IngestionPipeline,
    today_func: TodayProvider = today_taipei,
    concurrency: int = FOLLOW_UP_ACTION_CONCURRENCY,
    timeout_seconds: float = FOLLOW_UP_ACTION_TIMEOUT_SECONDS,
    summarize_execution_func: ExecutionSummaryFunc = summarize_follow_up_execution,
    single_action_executor: SingleActionExecutor | None = None,
    error_result_func: ErrorResultFunc | None = None,
) -> dict:
    error_result_func = error_result_func or follow_up_action_error_result
    today = today_func()
    result: dict[str, object] = {"actions": [action.to_dict() for action in actions], "results": {}}
    executable = [action for action in actions if action.action_type != "rerun_analysis"]
    semaphore = asyncio.Semaphore(concurrency)
    single_action_executor = single_action_executor or (
        lambda action, request, news_limit, today: execute_single_follow_up_action(
            action,
            request,
            news_limit,
            today,
            pipeline_factory=pipeline_factory,
            error_result_func=error_result_func,
        )
    )

    async def run_action(action: FollowUpExecutorAction) -> tuple[str, dict]:
        result_key = follow_up_result_key(action, request)
        tickers = list(action.tickers)
        try:
            async with semaphore:
                action_result = await asyncio.wait_for(
                    single_action_executor(action, request, news_limit, today),
                    timeout=timeout_seconds,
                )
        except asyncio.TimeoutError:
            action_result = error_result_func(
                action,
                tickers,
                f"補強任務超過 {timeout_seconds:g} 秒，已先記錄為可重試缺口。",
                "timeout",
            )
        except Exception as exc:
            action_result = error_result_func(
                action,
                tickers,
                str(exc) or exc.__class__.__name__,
                "execution_error",
            )
        return result_key, action_result

    for result_key, action_result in await asyncio.gather(*(run_action(action) for action in executable)):
        result["results"][result_key] = action_result
    result["execution_summary"] = summarize_execution_func(result)
    return result


async def execute_single_follow_up_action(
    action: FollowUpExecutorAction,
    request: ReportRequest,
    news_limit: int,
    today: date,
    *,
    pipeline_factory: PipelineFactory = IngestionPipeline,
    error_result_func: ErrorResultFunc | None = None,
) -> dict:
    error_result_func = error_result_func or follow_up_action_error_result
    pipeline = pipeline_factory()
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
    return error_result_func(action, tickers, f"未知補強任務：{action.action_type}", "unknown_action")


def follow_up_result_key(action: FollowUpExecutorAction, request: ReportRequest) -> str:
    tickers = list(action.tickers)
    return action.action_type if not tickers else f"{action.action_type}:{','.join(tickers)}"


def follow_up_action_error_result(
    action: FollowUpExecutorAction,
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
