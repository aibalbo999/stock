from __future__ import annotations

from datetime import date

from app.core.config import get_settings
from app.models.schemas import NewsDocument


class VectorStore:
    def __init__(self, collection_name: str = "ai_supply_chain_news") -> None:
        self.settings = get_settings()
        self.collection_name = collection_name
        self._fallback_docs: list[NewsDocument] = []
        if not self.settings.use_chroma:
            self.collection = None
            return
        try:
            import chromadb

            client = chromadb.PersistentClient(path=str(self.settings.vector_db_path))
            self.collection = client.get_or_create_collection(collection_name)
        except Exception:
            self.collection = None

    def upsert_documents(self, documents: list[NewsDocument]) -> None:
        if not documents:
            return
        if self.collection is None:
            self._fallback_docs.extend(documents)
            return

        self.collection.upsert(
            ids=[document.id for document in documents],
            documents=[document.text for document in documents],
            metadatas=[
                {
                    "title": document.title,
                    "publisher": document.source.publisher or "",
                    "url": document.source.url or "",
                    "published_at": document.source.published_at.isoformat()
                    if document.source.published_at
                    else "",
                }
                for document in documents
            ],
        )

    def search(self, query: str, n_results: int = 8) -> list[NewsDocument]:
        if self.collection is None:
            terms = [term.lower() for term in query.split()]
            ranked = [
                document
                for document in self._fallback_docs
                if any(term in document.text.lower() or term in document.title.lower() for term in terms)
            ]
            return ranked[:n_results]

        result = self.collection.query(query_texts=[query], n_results=n_results)
        documents: list[NewsDocument] = []
        for idx, text in enumerate(result.get("documents", [[]])[0]):
            metadata = result.get("metadatas", [[]])[0][idx]
            published_at = metadata.get("published_at") or None
            documents.append(
                NewsDocument(
                    id=result.get("ids", [[]])[0][idx],
                    title=metadata.get("title", ""),
                    text=text,
                    source={
                        "title": metadata.get("title", ""),
                        "url": metadata.get("url") or None,
                        "publisher": metadata.get("publisher") or None,
                        "published_at": date.fromisoformat(published_at) if published_at else None,
                    },
                )
            )
        return documents
