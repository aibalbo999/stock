from __future__ import annotations

from importlib.util import find_spec

from app.core.config import get_settings
from app.rag.reranker import RagReranker
from app.rag.vector_store import VectorStore
from app.services.llm_attempts import summarize_llm_attempts


def summarize_llm_status(llm_result: object | None) -> dict | None:
    if llm_result is None:
        return None
    attempts = getattr(llm_result, "attempts", ())
    return {
        "fallback": bool(getattr(llm_result, "fallback", False)),
        "model": getattr(llm_result, "model", None),
        "key_index": getattr(llm_result, "key_index", None),
        "provider": getattr(llm_result, "provider", None),
        "attempt_summary": summarize_llm_attempts(attempts),
        "attempts": list(attempts[-10:]) if isinstance(attempts, (tuple, list)) else [],
        "observability": getattr(llm_result, "observability", {}) or {},
    }


def rag_runtime_status() -> dict:
    settings = get_settings()
    embedding_status = VectorStore.runtime_embedding_provider_status(settings)
    retrieval_status = VectorStore.retrieval_runtime_status(settings)
    chroma_available = _module_available("chromadb")
    persistent_collection_enabled = _rag_persistent_collection_enabled(
        settings,
        embedding_status,
        chroma_available,
    )
    reranker_status = RagReranker().status()
    return {
        "use_chroma": bool(settings.use_chroma),
        "chroma_available": chroma_available,
        "persistent_collection_enabled": persistent_collection_enabled,
        "retrieval_mode": "chroma_hybrid" if persistent_collection_enabled else "memory_hybrid",
        "retrieval_status": retrieval_status,
        "embedding_status": embedding_status,
        "reranker_status": reranker_status,
    }


def _rag_persistent_collection_enabled(
    settings, embedding_status: dict, chroma_available: bool
) -> bool:
    if not settings.use_chroma:
        return False
    if not chroma_available:
        return False
    if not embedding_status.get("custom_embedding_requested"):
        return True
    if embedding_status.get("custom_embedding_enabled"):
        return True
    return bool(settings.rag_allow_chroma_default_embedding_fallback)


def _module_available(module_name: str) -> bool:
    try:
        return find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False


__all__ = [
    "rag_runtime_status",
    "summarize_llm_status",
]
