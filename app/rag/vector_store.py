from __future__ import annotations

import math
import re
from collections import Counter
from datetime import date
from importlib.util import find_spec
from time import monotonic
from typing import Any, Callable
from urllib.parse import urlparse

from app.core.config import get_settings
from app.models.schemas import NewsDocument
from app.rag.embedding_provider_config import (
    build_embedding_function,
    collection_name_for_settings,
    collection_name_part,
    embedding_api_key,
    embedding_dependency_available,
    embedding_factory,
    embedding_provider_spec,
    embedding_provider_status,
    index_schema_version,
    normalized_embedding_provider,
)
from app.rag.reranker import RagReranker
from app.rag.timeouts import RagOperationTimeout, run_with_timeout
from app.services.entity_mapping import CONFUSING_ENTITY_PREFIXES, alias_matches_text
from app.services.source_quality import (
    SOURCE_CREDIBILITY_WEIGHTS,
    source_credibility_tier_for_document,
    source_credibility_weight_for_document,
)

TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_+.-]*|[\u4e00-\u9fff]+")
EMBEDDING_BODY_MARKER = "\n\n內文："


class VectorStore:
    UPSERT_BATCH_SIZE = 100

    def __init__(self, collection_name: str = "ai_supply_chain_news") -> None:
        self.settings = get_settings()
        self.collection_name = collection_name
        self._fallback_docs: list[NewsDocument] = []
        self.reranker = RagReranker()
        self.last_retrieval_trace: dict[str, Any] = {}
        self.last_upsert_error: str | None = None
        self._chroma_query_disabled_for_session = False
        self._chroma_get_disabled_for_session = False
        self.embedding_status = self.runtime_embedding_provider_status(self.settings)
        if not self.settings.use_chroma:
            self.collection = None
            return
        try:
            import chromadb

            embedding_function = self._embedding_function()
            if self._should_disable_chroma_default_fallback(embedding_function):
                self.collection = None
                return
            self.collection_name = self._collection_name_for_settings(
                collection_name,
                self.settings,
                embedding_function_available=embedding_function is not None,
            )
            client = self._chroma_client(chromadb)
            self.collection = client.get_or_create_collection(
                self.collection_name,
                embedding_function=embedding_function,
                metadata={
                    "embedding_provider": (
                        self.settings.rag_embedding_provider if embedding_function else "chroma_default"
                    ),
                    "embedding_model": (
                        self.settings.rag_embedding_model if embedding_function else "chroma_default"
                    ),
                    "search": "hybrid-vector-bm25",
                    "index_schema_version": self._index_schema_version(self.settings),
                    "document_identity_header": "title_source_date_company_body",
                },
            )
        except Exception:
            self.collection = None

    def upsert_documents(self, documents: list[NewsDocument]) -> None:
        if not documents:
            return
        if self.collection is None:
            self._fallback_docs.extend(documents)
            return
        metadatas = [self._metadata_for_document(document) for document in documents]

        for start in range(0, len(documents), self.UPSERT_BATCH_SIZE):
            batch_documents = documents[start : start + self.UPSERT_BATCH_SIZE]
            batch_metadatas = metadatas[start : start + self.UPSERT_BATCH_SIZE]
            try:
                self._collection_upsert(
                    ids=[document.id for document in batch_documents],
                    documents=[
                        self._embedding_document_text(document, metadata)
                        for document, metadata in zip(batch_documents, batch_metadatas)
                    ],
                    metadatas=batch_metadatas,
                )
            except RagOperationTimeout as exc:
                self.last_upsert_error = str(exc)
                self.collection = None
                self._fallback_docs.extend(documents[start:])
                return
            except Exception as exc:
                if not self._is_embedding_quota_error(exc):
                    raise
                self.last_upsert_error = str(exc)
                self.collection = None
                self._fallback_docs.extend(documents[start:])
                return

    def search(
        self,
        query: str,
        n_results: int = 8,
        target_tickers: list[str] | None = None,
        target_aliases: dict[str, list[str]] | None = None,
    ) -> list[NewsDocument]:
        started_at = monotonic()
        if self.collection is None or getattr(self, "_chroma_query_disabled_for_session", False):
            return self._hybrid_rank(
                query,
                [],
                self._fallback_docs,
                n_results,
                target_tickers,
                target_aliases,
                started_at=started_at,
            )

        semantic_limit = max(n_results, int(self.settings.rag_rerank_top_k))
        try:
            result = self._collection_query(
                query_texts=[query],
                n_results=semantic_limit,
                include=["documents", "metadatas", "distances"],
            )
        except RagOperationTimeout as exc:
            self.last_upsert_error = str(exc)
            self._chroma_query_disabled_for_session = True
            return self._hybrid_rank(
                query,
                [],
                self._keyword_corpus(),
                n_results,
                target_tickers,
                target_aliases,
                started_at=started_at,
            )
        except Exception as exc:
            if not self._is_embedding_quota_error(exc):
                raise
            self.last_upsert_error = str(exc)
            return self._hybrid_rank(
                query,
                [],
                self._keyword_corpus(),
                n_results,
                target_tickers,
                target_aliases,
                started_at=started_at,
            )
        vector_hits = self._documents_from_query_result(result)
        if not self.settings.rag_hybrid_search_enabled:
            documents = self._filter_by_target_tickers(
                [document for document, _score in vector_hits[:semantic_limit]],
                target_tickers,
                target_aliases,
            )
            results = self.reranker.rerank(query, documents, n_results)
            self.last_retrieval_trace = {
                "query": query,
                "strategy": "vector-only",
                "duration_ms": self._elapsed_ms(started_at),
                "target_tickers": list(target_tickers or []),
                "vector_hit_count": len(vector_hits),
                "candidate_count": len(documents),
                "returned_count": len(results),
                "candidates": [
                    self._trace_row(
                        document,
                        vector_score=score,
                        rank=index + 1,
                        pre_source_score=score,
                        source_quality_multiplier=1.0,
                        source_quality_tier="not_applied_vector_only",
                        final_score=score,
                    )
                    for index, (document, score) in enumerate(vector_hits)
                    if document in documents
                ][:20],
                "result_ids": [self._document_key(document) for document in results],
                "reranker_status": getattr(self.reranker, "last_status", {}),
            }
            return results

        keyword_corpus = self._keyword_corpus()
        return self._hybrid_rank(
            query,
            vector_hits,
            keyword_corpus,
            n_results,
            target_tickers,
            target_aliases,
            started_at=started_at,
        )

    def _keyword_corpus(self) -> list[NewsDocument]:
        if self.collection is None or getattr(self, "_chroma_get_disabled_for_session", False):
            return list(self._fallback_docs)
        try:
            result = self._collection_get(
                limit=max(1, int(self.settings.rag_keyword_corpus_limit)),
                include=["documents", "metadatas"],
            )
        except RagOperationTimeout as exc:
            self.last_upsert_error = str(exc)
            self._chroma_get_disabled_for_session = True
            return list(self._fallback_docs)
        except Exception:
            return []
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
            documents.append(
                self._document_from_metadata(ids[idx] if idx < len(ids) else "", text, metadata)
            )
        return documents

    def _documents_from_query_result(self, result: dict) -> list[tuple[NewsDocument, float]]:
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
                    self._document_from_metadata(ids[idx] if idx < len(ids) else "", text, metadata),
                    score,
                )
            )
        return documents

    @staticmethod
    def _document_from_metadata(document_id: str, text: str, metadata: dict) -> NewsDocument:
        published_at = metadata.get("published_at") or None
        return NewsDocument(
            id=document_id,
            title=metadata.get("title", ""),
            text=VectorStore._stored_document_body(text),
            source={
                "title": metadata.get("title", ""),
                "url": metadata.get("url") or None,
                "publisher": metadata.get("publisher") or None,
                "published_at": date.fromisoformat(published_at) if published_at else None,
            },
            entity_tickers=VectorStore._metadata_list(metadata.get("entity_tickers")),
            entity_names=VectorStore._metadata_list(metadata.get("entity_names")),
        )

    @staticmethod
    def _metadata_for_document(document: NewsDocument) -> dict:
        entity_tickers = list(document.entity_tickers)
        entity_names = list(document.entity_names)
        if not entity_tickers:
            try:
                from app.services.entity_mapping import EntityMapper

                matches = EntityMapper().match_document(document)
            except Exception:
                matches = []
            entity_tickers = [match.ticker for match in matches]
            entity_names = [match.name for match in matches]
        return {
            "title": document.title,
            "publisher": document.source.publisher or "",
            "url": document.source.url or "",
            "published_at": document.source.published_at.isoformat()
            if document.source.published_at
            else "",
            "entity_tickers": ",".join(dict.fromkeys(entity_tickers)),
            "entity_names": ",".join(dict.fromkeys(entity_names)),
        }

    @staticmethod
    def _metadata_list(value: object) -> list[str]:
        if value is None:
            return []
        raw_values = value if isinstance(value, list) else str(value).split(",")
        return list(dict.fromkeys(str(item).strip() for item in raw_values if str(item).strip()))

    @staticmethod
    def _embedding_document_text(document: NewsDocument, metadata: dict | None = None) -> str:
        metadata = metadata or VectorStore._metadata_for_document(document)
        entity_tickers = VectorStore._metadata_list(metadata.get("entity_tickers"))
        entity_names = VectorStore._metadata_list(metadata.get("entity_names"))
        entity_labels = [
            " ".join(part for part in (ticker, name) if part).strip()
            for ticker, name in zip(entity_tickers, entity_names)
        ]
        if len(entity_tickers) > len(entity_names):
            entity_labels.extend(entity_tickers[len(entity_names) :])
        elif len(entity_names) > len(entity_tickers):
            entity_labels.extend(entity_names[len(entity_tickers) :])
        parts = [
            f"標題：{document.title}" if document.title else "",
            f"來源：{document.source.publisher}" if document.source.publisher else "",
            (
                f"日期：{document.source.published_at.isoformat()}"
                if document.source.published_at
                else ""
            ),
            f"公司對應：{'、'.join(entity_labels)}" if entity_labels else "",
        ]
        header = "\n".join(part for part in parts if part)
        if not header:
            return document.text
        return f"{header}{EMBEDDING_BODY_MARKER}{document.text}"

    @staticmethod
    def _is_embedding_quota_error(exc: Exception) -> bool:
        status_code = getattr(exc, "status_code", None)
        text = str(exc)
        return status_code == 429 or "RESOURCE_EXHAUSTED" in text or "Quota exceeded" in text

    @staticmethod
    def _stored_document_body(text: str) -> str:
        if EMBEDDING_BODY_MARKER not in text:
            return text
        return text.split(EMBEDDING_BODY_MARKER, 1)[1]

    def _hybrid_rank(
        self,
        query: str,
        vector_hits: list[tuple[NewsDocument, float]],
        keyword_corpus: list[NewsDocument],
        n_results: int,
        target_tickers: list[str] | None = None,
        target_aliases: dict[str, list[str]] | None = None,
        *,
        started_at: float | None = None,
    ) -> list[NewsDocument]:
        started_at = started_at if started_at is not None else monotonic()
        vector_weight = max(0.0, float(self.settings.rag_vector_weight))
        keyword_weight = max(0.0, float(self.settings.rag_keyword_weight))
        original_vector_hit_count = len(vector_hits)
        original_keyword_corpus_count = len(keyword_corpus)
        vector_hits = [
            (document, score)
            for document, score in vector_hits
            if self._document_matches_target_tickers(document, target_tickers, target_aliases)
        ]
        keyword_corpus = self._filter_by_target_tickers(keyword_corpus, target_tickers, target_aliases)
        vector_scores = {self._document_key(document): score for document, score in vector_hits}
        keyword_scores = self._bm25_scores(query, keyword_corpus)
        max_keyword = max(keyword_scores.values(), default=0.0)
        ranked: dict[str, dict] = {}

        for document, score in vector_hits:
            key = self._document_key(document)
            ranked[key] = {
                "document": document,
                "vector_score": score,
                "keyword_raw_score": 0.0,
                "keyword_score": 0.0,
                "score": vector_weight * score,
            }

        for document in keyword_corpus:
            key = self._document_key(document)
            raw_keyword_score = keyword_scores.get(key, 0.0)
            if raw_keyword_score <= 0 and key not in vector_scores:
                continue
            keyword_score = raw_keyword_score / max_keyword if max_keyword > 0 else 0.0
            current = ranked.setdefault(
                key,
                {
                    "document": document,
                    "vector_score": 0.0,
                    "keyword_raw_score": 0.0,
                    "keyword_score": 0.0,
                    "score": 0.0,
                },
            )
            current["keyword_raw_score"] = raw_keyword_score
            current["keyword_score"] = keyword_score
            current["score"] += keyword_weight * keyword_score

        for item in ranked.values():
            item["pre_source_score"] = item["score"]
            item["source_quality_multiplier"] = self._source_quality_multiplier(item["document"])
            item["source_quality_tier"] = self._source_quality_tier(item["document"])
            item["score"] *= item["source_quality_multiplier"]

        ranked_items = sorted(
            ranked.values(),
            key=lambda item: (
                item["score"],
                item["document"].source.published_at or date.min,
                item["document"].title,
            ),
            reverse=True,
        )
        results = self.reranker.rerank(
            query,
            [item["document"] for item in ranked_items],
            n_results,
        )
        self.last_retrieval_trace = {
            "query": query,
            "strategy": "hybrid-vector-bm25-rerank",
            "duration_ms": self._elapsed_ms(started_at),
            "target_tickers": list(target_tickers or []),
            "vector_weight": vector_weight,
            "keyword_weight": keyword_weight,
            "vector_hit_count": original_vector_hit_count,
            "keyword_corpus_count": original_keyword_corpus_count,
            "target_filtered_vector_hit_count": len(vector_hits),
            "target_filtered_keyword_corpus_count": len(keyword_corpus),
            "candidate_count": len(ranked_items),
            "returned_count": len(results),
            "candidates": [
                self._trace_row(
                    item["document"],
                    rank=index + 1,
                    vector_score=float(item.get("vector_score") or 0.0),
                    keyword_raw_score=float(item.get("keyword_raw_score") or 0.0),
                    keyword_score=float(item.get("keyword_score") or 0.0),
                    pre_source_score=float(item.get("pre_source_score") or 0.0),
                    source_quality_multiplier=float(item.get("source_quality_multiplier") or 0.0),
                    source_quality_tier=str(item.get("source_quality_tier") or "unknown"),
                    final_score=float(item.get("score") or 0.0),
                )
                for index, item in enumerate(ranked_items[:20])
            ],
            "result_ids": [self._document_key(document) for document in results],
            "reranker_status": getattr(self.reranker, "last_status", {}),
        }
        return results

    @staticmethod
    def _elapsed_ms(started_at: float) -> float:
        return round(max(0.0, monotonic() - started_at) * 1000, 3)

    @classmethod
    def _trace_row(
        cls,
        document: NewsDocument,
        *,
        rank: int,
        vector_score: float = 0.0,
        keyword_raw_score: float = 0.0,
        keyword_score: float = 0.0,
        pre_source_score: float | None = None,
        source_quality_multiplier: float | None = None,
        source_quality_tier: str | None = None,
        final_score: float | None = None,
    ) -> dict:
        multiplier = (
            float(source_quality_multiplier)
            if source_quality_multiplier is not None
            else cls._source_quality_multiplier(document)
        )
        tier = source_quality_tier or cls._source_quality_tier(document)
        pre_source = (
            float(pre_source_score)
            if pre_source_score is not None
            else float(vector_score) + float(keyword_score)
        )
        return {
            "rank": rank,
            "id": cls._document_key(document),
            "title": document.title,
            "publisher": document.source.publisher,
            "published_at": (
                document.source.published_at.isoformat()
                if document.source.published_at
                else None
            ),
            "entity_tickers": list(document.entity_tickers),
            "entity_names": list(document.entity_names),
            "vector_score": float(vector_score),
            "keyword_raw_score": float(keyword_raw_score),
            "keyword_score": float(keyword_score),
            "pre_source_score": pre_source,
            "source_quality_multiplier": multiplier,
            "source_quality_tier": tier,
            "final_score": float(final_score) if final_score is not None else pre_source * multiplier,
        }

    @staticmethod
    def _source_quality_multiplier(document: NewsDocument) -> float:
        try:
            return max(0.0, float(source_credibility_weight_for_document(document)))
        except Exception:
            return SOURCE_CREDIBILITY_WEIGHTS["unknown"]

    @staticmethod
    def _source_quality_tier(document: NewsDocument) -> str:
        try:
            return source_credibility_tier_for_document(document)
        except Exception:
            return "unknown"

    @classmethod
    def _filter_by_target_tickers(
        cls,
        documents: list[NewsDocument],
        target_tickers: list[str] | None,
        target_aliases: dict[str, list[str]] | None = None,
    ) -> list[NewsDocument]:
        return [
            document
            for document in documents
            if cls._document_matches_target_tickers(document, target_tickers, target_aliases)
        ]

    @classmethod
    def _document_matches_target_tickers(
        cls,
        document: NewsDocument,
        target_tickers: list[str] | None,
        target_aliases: dict[str, list[str]] | None = None,
    ) -> bool:
        target = {str(ticker) for ticker in target_tickers or [] if str(ticker)}
        if not target:
            return True
        entity_tickers = {str(ticker) for ticker in document.entity_tickers if str(ticker)}
        if entity_tickers:
            return bool(entity_tickers & target)
        aliases_by_ticker = cls._target_aliases_by_ticker(sorted(target), target_aliases)
        haystack = f"{document.title}\n{document.text}".lower()
        return any(
            alias_matches_text(haystack, alias)
            for ticker in target
            for alias in aliases_by_ticker.get(ticker, [ticker])
            if alias
        )

    @staticmethod
    def _target_aliases_by_ticker(
        target_tickers: list[str],
        target_aliases: dict[str, list[str]] | None = None,
    ) -> dict[str, list[str]]:
        aliases_by_ticker = {ticker: [ticker] for ticker in target_tickers if ticker}
        for ticker, aliases in (target_aliases or {}).items():
            if ticker not in aliases_by_ticker:
                continue
            aliases_by_ticker[ticker].extend(str(alias) for alias in aliases if str(alias))
        try:
            from app.services.whitelist import SupplyChainWhitelist

            companies = {company.ticker: company for company in SupplyChainWhitelist().companies()}
        except Exception:
            companies = {}
        for ticker in target_tickers:
            company = companies.get(ticker)
            if company is None:
                continue
            aliases_by_ticker.setdefault(ticker, [ticker]).extend([company.name, *company.aliases])
        return {
            ticker: list(dict.fromkeys(alias for alias in aliases if alias))
            for ticker, aliases in aliases_by_ticker.items()
        }

    @classmethod
    def _bm25_scores(cls, query: str, documents: list[NewsDocument]) -> dict[str, float]:
        query_terms = cls._tokenize(query)
        if not query_terms or not documents:
            return {}
        doc_terms = [cls._tokenize(cls._keyword_document_text(document)) for document in documents]
        doc_lengths = [len(terms) or 1 for terms in doc_terms]
        avg_doc_length = sum(doc_lengths) / len(doc_lengths)
        document_frequency: Counter[str] = Counter()
        for terms in doc_terms:
            document_frequency.update(set(terms))

        scores: dict[str, float] = {}
        query_counter = Counter(query_terms)
        for document, terms, doc_length in zip(documents, doc_terms, doc_lengths):
            term_counts = Counter(terms)
            score = 0.0
            for term, query_count in query_counter.items():
                frequency = term_counts.get(term, 0)
                if frequency <= 0:
                    continue
                idf = math.log(
                    1
                    + (len(documents) - document_frequency[term] + 0.5)
                    / (document_frequency[term] + 0.5)
                )
                denominator = frequency + 1.2 * (1 - 0.75 + 0.75 * doc_length / avg_doc_length)
                score += query_count * idf * (frequency * 2.2 / denominator)
            score += cls._exact_phrase_boost(query, document)
            if score > 0:
                scores[cls._document_key(document)] = score
        return scores

    @staticmethod
    def _keyword_document_text(document: NewsDocument) -> str:
        identity = " ".join([*document.entity_tickers, *document.entity_names])
        return "\n".join(
            part
            for part in (
                document.title,
                document.source.publisher or "",
                identity,
                document.text,
            )
            if part
        )

    @staticmethod
    def _exact_phrase_boost(query: str, document: NewsDocument) -> float:
        haystack = VectorStore._keyword_document_text(document).lower()
        boost = 0.0
        for raw_term in query.split():
            term = raw_term.strip().lower()
            if len(term) >= 2 and alias_matches_text(haystack, term):
                boost += 0.6 if term.isdigit() else 0.3
        return boost

    @classmethod
    def _tokenize(cls, text: str) -> list[str]:
        tokens: list[str] = []
        for match in TOKEN_RE.findall(text.lower()):
            if re.fullmatch(r"[\u4e00-\u9fff]+", match):
                if len(match) <= 4:
                    tokens.append(match)
                for size in (2, 3, 4):
                    if len(match) >= size:
                        for index in range(len(match) - size + 1):
                            token = match[index : index + size]
                            if cls._is_confusing_entity_prefix_token(match, token, index):
                                continue
                            tokens.append(token)
            elif len(match) >= 2:
                tokens.append(match)
        return tokens

    @staticmethod
    def _is_confusing_entity_prefix_token(text: str, token: str, index: int) -> bool:
        confusing_prefixes = CONFUSING_ENTITY_PREFIXES.get(token, ())
        return any(text.startswith(prefix.lower(), index) for prefix in confusing_prefixes)

    @staticmethod
    def _document_key(document: NewsDocument) -> str:
        return document.id or document.source.url or f"{document.title}:{document.source.published_at or ''}"

    def _embedding_function(self):
        embedding_functions = self._chromadb_embedding_functions_module()
        self.embedding_status = self.embedding_provider_status(self.settings, embedding_functions)
        embedding_function = self._build_embedding_function(self.settings, embedding_functions)
        if (
            embedding_function is None
            and self.embedding_status["custom_embedding_requested"]
            and self.embedding_status["custom_embedding_enabled"]
        ):
            self.embedding_status = {
                **self.embedding_status,
                "custom_embedding_enabled": False,
                "fallback_reason": "embedding_function_initialization_failed",
            }
        return embedding_function

    def _should_disable_chroma_default_fallback(self, embedding_function: Any | None) -> bool:
        if embedding_function is not None:
            return False
        if not self.embedding_status["custom_embedding_requested"]:
            return False
        if bool(getattr(self.settings, "rag_allow_chroma_default_embedding_fallback", False)):
            return False
        return True

    @staticmethod
    def _chromadb_embedding_functions_module() -> Any | None:
        try:
            from chromadb.utils import embedding_functions
        except Exception:
            return None
        return embedding_functions

    @classmethod
    def runtime_embedding_provider_status(cls, settings: Any | None = None) -> dict:
        return cls.embedding_provider_status(
            settings=settings,
            embedding_functions_module=cls._chromadb_embedding_functions_module(),
        )

    @staticmethod
    def _chroma_client(chromadb_module: Any, settings: Any | None = None) -> Any:
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
            database=str(getattr(settings, "chroma_database", "default_database") or "default_database"),
        )

    @staticmethod
    def retrieval_runtime_status(settings: Any | None = None) -> dict:
        settings = settings or get_settings()
        hybrid_enabled = bool(getattr(settings, "rag_hybrid_search_enabled", True))
        chroma_api_url = str(getattr(settings, "chroma_api_url", "") or "").strip()
        return {
            "strategy": "hybrid-vector-bm25" if hybrid_enabled else "vector-only",
            "storage_mode": "http" if chroma_api_url else "persistent",
            "chroma_api_url_configured": bool(chroma_api_url),
            "hybrid_search_enabled": hybrid_enabled,
            "bm25_enabled": hybrid_enabled,
            "tokenizer": "latin_terms+traditional_chinese_2_4_ngrams",
            "embedding_identity_header_enabled": True,
            "keyword_identity_fields": ["entity_tickers", "entity_names", "title", "publisher", "body"],
            "source_quality_weighting_enabled": True,
            "source_quality_weights": SOURCE_CREDIBILITY_WEIGHTS,
            "retrieval_trace_enabled": True,
            "retrieval_trace_fields": [
                "duration_ms",
                "vector_score",
                "keyword_raw_score",
                "keyword_score",
                "pre_source_score",
                "source_quality_multiplier",
                "final_score",
                "reranker_status",
            ],
            "index_schema_version": VectorStore._index_schema_version(settings),
            "collection_name_example": VectorStore._collection_name_for_settings(
                "ai_supply_chain_news",
                settings,
            ),
            "keyword_corpus_limit": int(getattr(settings, "rag_keyword_corpus_limit", 0)),
            "chroma_query_timeout_seconds": float(getattr(settings, "rag_chroma_query_timeout_seconds", 0.0)),
            "chroma_get_timeout_seconds": float(getattr(settings, "rag_chroma_get_timeout_seconds", 0.0)),
            "chroma_upsert_timeout_seconds": float(getattr(settings, "rag_chroma_upsert_timeout_seconds", 0.0)),
            "vector_weight": float(getattr(settings, "rag_vector_weight", 0.0)),
            "keyword_weight": float(getattr(settings, "rag_keyword_weight", 0.0)),
            "rerank_top_k": int(getattr(settings, "rag_rerank_top_k", 0)),
            "reranker_timeout_seconds": float(getattr(settings, "rag_reranker_timeout_seconds", 0.0)),
        }

    def _collection_query(self, **kwargs):
        return run_with_timeout(
            lambda: self.collection.query(**kwargs),
            self._timeout_seconds("rag_chroma_query_timeout_seconds"),
            "chroma_query",
        )

    def _collection_get(self, **kwargs):
        return run_with_timeout(
            lambda: self.collection.get(**kwargs),
            self._timeout_seconds("rag_chroma_get_timeout_seconds"),
            "chroma_get",
        )

    def _collection_upsert(self, **kwargs) -> None:
        run_with_timeout(
            lambda: self.collection.upsert(**kwargs),
            self._timeout_seconds("rag_chroma_upsert_timeout_seconds"),
            "chroma_upsert",
        )

    def _timeout_seconds(self, name: str) -> float:
        settings = getattr(self, "settings", None) or get_settings()
        return max(0.0, float(getattr(settings, name, 0.0)))

    @classmethod
    def embedding_provider_status(
        cls,
        settings: Any | None = None,
        embedding_functions_module: Any | None = None,
        dependency_checker: Callable[[str], bool] | None = None,
    ) -> dict:
        checker = dependency_checker or cls._default_embedding_dependency_checker
        return embedding_provider_status(
            settings=settings,
            embedding_functions_module=embedding_functions_module,
            dependency_checker=checker,
        )

    @classmethod
    def _build_embedding_function(
        cls,
        settings: Any,
        embedding_functions_module: Any,
        dependency_checker: Callable[[str], bool] | None = None,
    ):
        checker = dependency_checker or cls._default_embedding_dependency_checker
        return build_embedding_function(
            settings=settings,
            embedding_functions_module=embedding_functions_module,
            dependency_checker=checker,
        )

    @staticmethod
    def _normalized_embedding_provider(settings: Any) -> str:
        return normalized_embedding_provider(settings)

    @staticmethod
    def _embedding_provider_spec(provider: str) -> dict | None:
        return embedding_provider_spec(provider)

    @staticmethod
    def _embedding_factory(embedding_functions_module: Any | None, spec: dict) -> Any | None:
        return embedding_factory(embedding_functions_module, spec)

    @classmethod
    def _embedding_dependency_available(
        cls,
        dependency: str | None,
        dependency_checker: Callable[[str], bool] | None = None,
    ) -> bool | None:
        checker = dependency_checker or cls._default_embedding_dependency_checker
        return embedding_dependency_available(dependency, checker)

    @staticmethod
    def _embedding_api_key(settings: Any, provider: str) -> str | None:
        return embedding_api_key(settings, provider)

    @classmethod
    def _collection_name_for_settings(
        cls,
        collection_name: str,
        settings: Any,
        embedding_function_available: bool = True,
    ) -> str:
        return collection_name_for_settings(
            collection_name,
            settings,
            embedding_function_available=embedding_function_available,
        )

    @staticmethod
    def _index_schema_version(settings: Any) -> str:
        return index_schema_version(settings)

    @staticmethod
    def _collection_name_part(value: str, max_length: int) -> str:
        return collection_name_part(value, max_length)

    @staticmethod
    def _default_embedding_dependency_checker(module_name: str) -> bool:
        return find_spec(module_name) is not None
