from __future__ import annotations

from typing import Any, Callable
from urllib.parse import urlparse

from app.core.config import get_settings
from app.models.schemas import NewsDocument

DocumentFactory = Callable[[str, str, dict], NewsDocument]
TimeoutRunner = Callable[[Callable[[], Any], float, str], Any]


def chroma_client(chromadb_module: Any, settings: Any | None = None) -> Any:
    settings = settings or get_settings()
    api_url = str(getattr(settings, "chroma_api_url", "") or "").strip()
    if not api_url:
        return chromadb_module.PersistentClient(path=str(settings.vector_db_path))
    parsed = urlparse(api_url if "://" in api_url else f"http://{api_url}")
    host = parsed.hostname or parsed.netloc or parsed.path
    if not host:
        raise ValueError("CHROMA_API_URL must include a host")
    port = parsed.port or (443 if parsed.scheme == "https" else 8000)
    return chromadb_module.HttpClient(
        host=host,
        port=port,
        ssl=parsed.scheme == "https",
        tenant=str(getattr(settings, "chroma_tenant", "default_tenant") or "default_tenant"),
        database=str(
            getattr(settings, "chroma_database", "default_database") or "default_database"
        ),
    )


def get_or_create_collection(
    client: Any,
    collection_name: str,
    settings: Any,
    embedding_function: Any | None,
    index_schema_version: str,
) -> Any:
    return client.get_or_create_collection(
        collection_name,
        embedding_function=embedding_function,
        metadata=collection_metadata(
            settings=settings,
            embedding_function=embedding_function,
            index_schema_version=index_schema_version,
        ),
    )


def collection_metadata(
    settings: Any,
    embedding_function: Any | None,
    index_schema_version: str,
) -> dict:
    return {
        "embedding_provider": (
            settings.rag_embedding_provider if embedding_function else "chroma_default"
        ),
        "embedding_model": (
            settings.rag_embedding_model if embedding_function else "chroma_default"
        ),
        "search": "hybrid-vector-bm25",
        "index_schema_version": index_schema_version,
        "document_identity_header": "title_source_date_company_body",
    }


def collection_query(
    collection: Any,
    settings: Any,
    timeout_runner: TimeoutRunner,
    **kwargs,
) -> Any:
    return timeout_runner(
        lambda: collection.query(**kwargs),
        timeout_seconds(settings, "rag_chroma_query_timeout_seconds"),
        "chroma_query",
    )


def collection_get(
    collection: Any,
    settings: Any,
    timeout_runner: TimeoutRunner,
    **kwargs,
) -> Any:
    return timeout_runner(
        lambda: collection.get(**kwargs),
        timeout_seconds(settings, "rag_chroma_get_timeout_seconds"),
        "chroma_get",
    )


def collection_upsert(
    collection: Any,
    settings: Any,
    timeout_runner: TimeoutRunner,
    **kwargs,
) -> None:
    timeout_runner(
        lambda: collection.upsert(**kwargs),
        timeout_seconds(settings, "rag_chroma_upsert_timeout_seconds"),
        "chroma_upsert",
    )


def timeout_seconds(settings: Any, name: str) -> float:
    return max(0.0, float(getattr(settings, name, 0.0)))


def documents_from_get_result(
    result: dict,
    document_factory: DocumentFactory,
) -> list[NewsDocument]:
    documents = []
    ids = result.get("ids") or []
    texts = result.get("documents") or []
    metadatas = result.get("metadatas") or []
    for idx, text in enumerate(texts):
        metadata = (
            metadatas[idx]
            if idx < len(metadatas) and isinstance(metadatas[idx], dict)
            else {}
        )
        documents.append(document_factory(ids[idx] if idx < len(ids) else "", text, metadata))
    return documents


def documents_from_query_result(
    result: dict,
    document_factory: DocumentFactory,
) -> list[tuple[NewsDocument, float]]:
    texts = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    ids = (result.get("ids") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]
    documents: list[tuple[NewsDocument, float]] = []
    for idx, text in enumerate(texts):
        metadata = (
            metadatas[idx]
            if idx < len(metadatas) and isinstance(metadatas[idx], dict)
            else {}
        )
        distance = distances[idx] if idx < len(distances) and distances[idx] is not None else idx
        score = 1.0 / (1.0 + max(0.0, float(distance)))
        documents.append(
            (
                document_factory(ids[idx] if idx < len(ids) else "", text, metadata),
                score,
            )
        )
    return documents
