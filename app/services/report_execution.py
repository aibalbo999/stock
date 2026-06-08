from __future__ import annotations

from app.services.llm_attempts import summarize_llm_attempts


def report_execution_summary(generator: object) -> dict:
    evidence_documents = getattr(generator, "last_evidence_documents", None) or []
    excluded_low_quality = getattr(generator, "last_excluded_low_quality_documents", None) or []
    llm_result = getattr(generator, "last_llm_result", None)
    vector_store = getattr(generator, "vector_store", None)
    retrieval_trace = (
        getattr(vector_store, "last_retrieval_trace", None) if vector_store is not None else None
    )
    graph_reasoning_plan = getattr(generator, "last_graph_reasoning_plan", None)
    llm_status = None
    if llm_result is not None:
        llm_status = {
            "fallback": bool(getattr(llm_result, "fallback", False)),
            "model": getattr(llm_result, "model", None),
            "provider": getattr(llm_result, "provider", None),
            "key_index": getattr(llm_result, "key_index", None),
            "observability": getattr(llm_result, "observability", {}) or {},
            "attempt_summary": summarize_llm_attempts(getattr(llm_result, "attempts", ())),
            "attempts": list(getattr(llm_result, "attempts", ())[-10:]),
        }
    return {
        "filtered_tickers": list(getattr(generator, "last_filtered_tickers", None) or []),
        "dropped_tickers": list(getattr(generator, "last_dropped_tickers", None) or []),
        "evidence_count": len(evidence_documents),
        "excluded_low_quality_source_count": len(excluded_low_quality),
        "retrieval_trace": retrieval_trace,
        "graph_reasoning": graph_reasoning_plan,
        "llm": llm_status,
    }
