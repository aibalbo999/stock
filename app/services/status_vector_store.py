from __future__ import annotations

from importlib.util import find_spec
from typing import Callable
from urllib.parse import urlparse

from app.rag.reranker import RagReranker
from app.rag.vector_store import VectorStore


def vector_store_status(
    settings,
    *,
    module_available: Callable[[str], bool] = None,
) -> dict:
    module_available = module_available or _module_available
    embedding_status = VectorStore.runtime_embedding_provider_status(settings)
    retrieval_status = VectorStore.retrieval_runtime_status(settings)
    chroma_available = module_available("chromadb")
    reranker_status = RagReranker().status()
    return {
        "collector_path": "app/services/status_vector_store.py",
        "use_chroma": settings.use_chroma,
        "chroma_available": chroma_available,
        "path": str(settings.vector_db_path),
        "storage_mode": "http" if settings.chroma_api_url else "persistent",
        "chroma_api_url_configured": bool(settings.chroma_api_url),
        "chroma_api_url": _redact_url(settings.chroma_api_url),
        "chroma_tenant": settings.chroma_tenant,
        "chroma_database": settings.chroma_database,
        "embedding_provider": settings.rag_embedding_provider,
        "embedding_model": settings.rag_embedding_model,
        "allow_chroma_default_embedding_fallback": settings.rag_allow_chroma_default_embedding_fallback,
        "persistent_collection_enabled": _vector_store_persistent_collection_enabled(
            settings,
            embedding_status,
            chroma_available,
        ),
        "embedding_status": embedding_status,
        "retrieval_status": retrieval_status,
        "hybrid_search_enabled": settings.rag_hybrid_search_enabled,
        "vector_weight": settings.rag_vector_weight,
        "keyword_weight": settings.rag_keyword_weight,
        "rerank_top_k": settings.rag_rerank_top_k,
        "keyword_corpus_limit": settings.rag_keyword_corpus_limit,
        "reranker_provider": settings.rag_reranker_provider,
        "reranker_model": settings.rag_reranker_model,
        "reranker_text_limit": settings.rag_reranker_text_limit,
        "reranker_available": reranker_status["available"],
        "reranker_status": reranker_status,
    }


def _vector_store_persistent_collection_enabled(
    settings,
    embedding_status: dict,
    chroma_available: bool,
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


def _redact_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.password is None:
        return url
    netloc = parsed.hostname or ""
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    if parsed.username:
        netloc = f"{parsed.username}:***@{netloc}"
    return parsed._replace(netloc=netloc).geturl()
