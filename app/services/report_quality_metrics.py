from __future__ import annotations

from datetime import date

from app.services.report_quality_sources import date_to_text


def quality_gate_metrics(
    *,
    promoted_count: int,
    formal_supported_ratio: float,
    exploration_supported_ratio: float,
    formal_confidence_avg: object,
    formal_confidence_min: object,
    formal_low_confidence_count: int,
    source_count: int,
    missing_subtopic_count: int,
    weak_subtopic_count: int,
    market_coverage: float,
    monthly_coverage: float,
    financial_metrics_count: int,
    valuation_coverage: float,
    market_fresh_coverage: float,
    monthly_fresh_coverage: float,
    valuation_fresh_coverage: float,
    market_stale_count: int,
    monthly_revenue_stale_count: int,
    financial_metrics_stale_ticker_count: int,
    valuation_stale_count: int,
    stale_market_dataset_count: int,
    market_latest_only_count: int,
    monthly_revenue_latest_only_count: int,
    financial_metrics_latest_only_ticker_count: int,
    valuation_latest_only_count: int,
    latest_only_market_dataset_count: int,
    market_latest_trade_date: date | str | None,
    market_latest_trade_date_coverage: float | None,
    market_database_latest_trade_date: date | str | None,
    market_older_than_database_latest_count: int,
    market_trade_date_lag_days: int | None,
    market_trade_date_warning_suppressed: bool,
    leading_signal_coverage: float | None,
    company_filing_coverage: float | None,
    llm_status: dict,
    llm_fallback: bool | None,
    llm_observability: dict,
    rag_status: dict,
    rag_embedding_status: dict,
    rag_reranker_status: dict,
    rag_reranker_provider: str,
    rag_retrieval_status: dict,
    market_provider_summary: dict,
    source_quality: dict,
    plan_quality: dict,
) -> dict:
    attempt_summary = llm_status.get("attempt_summary") or {}
    return {
        "promoted_count": promoted_count,
        "candidate_supported_ratio": formal_supported_ratio,
        "exploration_candidate_supported_ratio": exploration_supported_ratio,
        "formal_confidence_avg": formal_confidence_avg,
        "formal_confidence_min": formal_confidence_min,
        "formal_low_confidence_count": formal_low_confidence_count,
        "dynamic_source_count": source_count,
        "missing_subtopic_count": missing_subtopic_count,
        "weak_subtopic_count": weak_subtopic_count,
        "market_coverage": market_coverage,
        "monthly_revenue_coverage": monthly_coverage,
        "financial_metrics_count": financial_metrics_count,
        "valuation_coverage": valuation_coverage,
        "market_fresh_coverage": market_fresh_coverage,
        "monthly_revenue_fresh_coverage": monthly_fresh_coverage,
        "valuation_fresh_coverage": valuation_fresh_coverage,
        "market_stale_count": market_stale_count,
        "monthly_revenue_stale_count": monthly_revenue_stale_count,
        "financial_metrics_stale_ticker_count": financial_metrics_stale_ticker_count,
        "valuation_stale_count": valuation_stale_count,
        "stale_market_dataset_count": stale_market_dataset_count,
        "market_latest_only_count": market_latest_only_count,
        "monthly_revenue_latest_only_count": monthly_revenue_latest_only_count,
        "financial_metrics_latest_only_ticker_count": financial_metrics_latest_only_ticker_count,
        "valuation_latest_only_count": valuation_latest_only_count,
        "latest_only_market_dataset_count": latest_only_market_dataset_count,
        "market_latest_trade_date": date_to_text(market_latest_trade_date),
        "market_latest_trade_date_coverage": market_latest_trade_date_coverage,
        "market_database_latest_trade_date": date_to_text(market_database_latest_trade_date),
        "market_older_than_database_latest_count": int(
            market_older_than_database_latest_count or 0
        ),
        "market_trade_date_lag_days": market_trade_date_lag_days,
        "market_trade_date_warning_suppressed": market_trade_date_warning_suppressed,
        "leading_signal_coverage": leading_signal_coverage,
        "company_filing_coverage": company_filing_coverage,
        "llm_analysis_status": _llm_analysis_status(llm_status, llm_fallback),
        "llm_model": llm_status.get("model"),
        "llm_key_index": llm_status.get("key_index"),
        "llm_provider": llm_status.get("provider"),
        "llm_attempt_count": attempt_summary.get("attempt_count"),
        "llm_failed_attempt_count": attempt_summary.get("failed_attempt_count"),
        "llm_success_after_failure": attempt_summary.get("success_after_failure"),
        "llm_retry_used": attempt_summary.get("retry_used"),
        "llm_fallback_path_used": attempt_summary.get("fallback_path_used"),
        "llm_provider_fallback_used": attempt_summary.get("provider_fallback_used"),
        "llm_model_fallback_used": attempt_summary.get("model_fallback_used"),
        "llm_final_outcome": attempt_summary.get("final_outcome"),
        "llm_primary_failure_category": attempt_summary.get("primary_failure_category"),
        "llm_retryable_failure_count": attempt_summary.get("retryable_failure_count"),
        "llm_latency_ms": llm_observability.get("latency_ms"),
        "llm_input_token_estimate": llm_observability.get("input_token_estimate"),
        "llm_output_token_estimate": llm_observability.get("output_token_estimate"),
        "llm_total_token_estimate": llm_observability.get("total_token_estimate"),
        "llm_estimated_cost_usd": llm_observability.get("estimated_cost_usd"),
        "llm_cost_tracking_mode": llm_observability.get("cost_tracking_mode"),
        "llm_external_trace_provider": llm_observability.get("external_trace_provider"),
        "rag_retrieval_mode": rag_status.get("retrieval_mode"),
        "rag_retrieval_strategy": rag_retrieval_status.get("strategy"),
        "rag_hybrid_search_enabled": rag_retrieval_status.get("hybrid_search_enabled"),
        "rag_bm25_enabled": rag_retrieval_status.get("bm25_enabled"),
        "rag_keyword_corpus_limit": rag_retrieval_status.get("keyword_corpus_limit"),
        "rag_vector_weight": rag_retrieval_status.get("vector_weight"),
        "rag_keyword_weight": rag_retrieval_status.get("keyword_weight"),
        "rag_rerank_top_k": rag_retrieval_status.get("rerank_top_k"),
        "rag_use_chroma": rag_status.get("use_chroma"),
        "rag_chroma_available": rag_status.get("chroma_available"),
        "rag_persistent_collection_enabled": rag_status.get("persistent_collection_enabled"),
        "rag_embedding_provider": rag_embedding_status.get("provider"),
        "rag_embedding_enabled": rag_embedding_status.get("custom_embedding_enabled"),
        "rag_embedding_fallback_reason": rag_embedding_status.get("fallback_reason"),
        "rag_reranker_provider": rag_reranker_status.get("provider"),
        "rag_reranker_execution_mode": rag_reranker_status.get("execution_mode"),
        "rag_reranker_available": rag_reranker_status.get("available"),
        "rag_reranker_model_ready": _rag_reranker_model_ready(
            rag_reranker_status, rag_reranker_provider
        ),
        "rag_reranker_quality_tier": rag_reranker_status.get("quality_tier"),
        "rag_reranker_keyword_fallback": rag_reranker_status.get("keyword_fallback"),
        "rag_reranker_model_gap": rag_reranker_status.get("model_reranker_gap"),
        "rag_reranker_fallback_reason": rag_reranker_status.get("fallback_reason"),
        "market_provider_summary": market_provider_summary,
        "source_unique_publishers": source_quality.get("unique_publisher_count"),
        "source_timestamp_coverage": source_quality.get("timestamp_coverage"),
        "source_recent_coverage": source_quality.get("recent_coverage"),
        "source_lookback_days": source_quality.get("lookback_days"),
        "source_high_credibility_ratio": source_quality.get("high_credibility_ratio"),
        "source_low_credibility_ratio": source_quality.get("low_credibility_ratio"),
        "source_average_credibility": source_quality.get("average_credibility"),
        "discovery_plan_status": plan_quality.get("status") if plan_quality else None,
        "discovery_plan_score": plan_quality.get("score") if plan_quality else None,
    }


def _llm_analysis_status(llm_status: dict, llm_fallback: bool | None) -> str | None:
    if llm_fallback:
        return "fallback"
    if llm_status:
        return "enabled"
    return None


def _rag_reranker_model_ready(
    rag_reranker_status: dict,
    rag_reranker_provider: str,
) -> bool | None:
    if "model_reranker_ready" in rag_reranker_status:
        return rag_reranker_status.get("model_reranker_ready")
    if rag_reranker_provider in {"", "none", "disabled", "off"}:
        return None
    return bool(rag_reranker_status.get("available")) and rag_reranker_provider not in {
        "keyword",
        "hybrid",
    }


__all__ = ["quality_gate_metrics"]
