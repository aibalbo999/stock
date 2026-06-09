from __future__ import annotations


def rag_quality_warnings(rag_status: dict | None) -> list[str]:
    if not rag_status:
        return []
    warnings: list[str] = []
    embedding_status = rag_status.get("embedding_status") or {}
    reranker_status = rag_status.get("reranker_status") or {}
    reranker_provider = normalized_rag_reranker_provider(reranker_status)
    if rag_status.get("use_chroma") and not rag_status.get("chroma_available"):
        warnings.append("RAG 向量庫套件不可用，檢索已退回本輪資料與關鍵字排序")
    if (
        rag_status.get("use_chroma")
        and embedding_status.get("custom_embedding_requested")
        and not embedding_status.get("custom_embedding_enabled")
    ):
        if embedding_status.get("chroma_default_fallback_allowed"):
            warnings.append("RAG 自訂 embedding 未啟用，已退回 Chroma 預設模型，繁中檢索信心需下修")
        else:
            warnings.append("RAG 自訂 embedding 未啟用，已停用持久化向量庫並退回關鍵字檢索")
    if reranker_status and reranker_provider in {"keyword", "hybrid"}:
        warnings.append(
            "RAG reranker 目前僅使用關鍵字排序，尚未啟用模型級重排序，來源排序信心需人工覆核"
        )
    elif (
        reranker_status
        and reranker_status.get("keyword_fallback")
        and not reranker_status.get("model_reranker_ready")
    ):
        warnings.append(
            "RAG reranker auto 模式已退回關鍵字排序，模型級重排序尚未可用，來源排序信心需人工覆核"
        )
    elif (
        reranker_status
        and reranker_provider not in {"", "none", "disabled", "off"}
        and not reranker_status.get("model_reranker_ready", reranker_status.get("available"))
    ):
        warnings.append("RAG reranker 未啟用或推論失敗，檢索排序信心需人工覆核")
    return warnings


def normalized_rag_reranker_provider(reranker_status: dict | None) -> str:
    reranker_status = reranker_status or {}
    return (
        str(reranker_status.get("normalized_provider") or reranker_status.get("provider") or "")
        .lower()
        .replace("-", "_")
    )
