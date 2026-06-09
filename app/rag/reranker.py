from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from functools import lru_cache
from importlib.util import find_spec
from typing import Any, Optional

from app.core.config import get_settings
from app.models.schemas import NewsDocument
from app.rag.keyword_reranker import (
    OFFICIAL_SOURCE_HINTS as _OFFICIAL_SOURCE_HINTS,
    TOKEN_RE as _TOKEN_RE,
    document_text,
    exact_query_terms,
    is_confusing_entity_prefix_token,
    keyword_rerank,
    keyword_score,
    source_quality_adjustment,
    tokenize,
)
from app.rag.llm_reranker import apply_llm_ranked_indexes, llm_rerank_prompt, parse_llm_ranked_indexes
from app.rag.reranker_status import (
    AUTO_RERANKER_PROVIDERS,
    COHERE_RERANKER_PROVIDERS,
    CROSS_ENCODER_RERANKER_PROVIDERS,
    DISABLED_RERANKER_PROVIDERS,
    KEYWORD_RERANKER_PROVIDERS,
    LLM_RERANKER_PROVIDERS,
    MODEL_NOT_PROVIDED as _MODEL_NOT_PROVIDED,
    RerankerStatusBuilder,
    auto_candidate_summary,
)
from app.rag.timeouts import RagOperationTimeout, run_with_timeout


TOKEN_RE = _TOKEN_RE
OFFICIAL_SOURCE_HINTS = _OFFICIAL_SOURCE_HINTS


class RagReranker:
    def __init__(
        self,
        provider: str | None = None,
        model_name: str | None = None,
        text_limit: int | None = None,
        cross_encoder_factory: Callable[[str], object] | None = None,
        cohere_client_factory: Callable[[str], object] | None = None,
        llm_client_factory: Callable[[], object] | None = None,
        cohere_api_key: Optional[str] = None,
        llm_reranker_enabled: bool | None = None,
        llm_reranker_max_documents: int | None = None,
    ) -> None:
        settings = get_settings()
        self.provider = (provider if provider is not None else settings.rag_reranker_provider).strip()
        self.model_name = (model_name if model_name is not None else settings.rag_reranker_model).strip()
        self.text_limit = int(text_limit if text_limit is not None else settings.rag_reranker_text_limit)
        self.timeout_seconds = max(0.0, float(getattr(settings, "rag_reranker_timeout_seconds", 15.0)))
        self.cross_encoder_factory = cross_encoder_factory
        self.cohere_client_factory = cohere_client_factory
        self.llm_client_factory = llm_client_factory
        self.cohere_api_key = cohere_api_key if cohere_api_key is not None else (settings.cohere_api_key or "")
        self.llm_reranker_enabled = bool(
            settings.rag_llm_reranker_enabled if llm_reranker_enabled is None else llm_reranker_enabled
        )
        self.llm_reranker_max_documents = max(
            1,
            int(
                settings.rag_llm_reranker_max_documents
                if llm_reranker_max_documents is None
                else llm_reranker_max_documents
            ),
        )
        self._llm_disabled_for_session = False
        self.last_status = self._base_status()

    def rerank(
        self,
        query: str,
        documents: list[NewsDocument],
        n_results: int,
    ) -> list[NewsDocument]:
        if not documents:
            self.last_status = self.status()
            return []
        provider = self._provider_key()
        limit = max(1, int(n_results))
        if provider in AUTO_RERANKER_PROVIDERS:
            return self._auto_rerank(query, documents, limit)
        if provider in DISABLED_RERANKER_PROVIDERS | KEYWORD_RERANKER_PROVIDERS:
            self.last_status = self.status()
            if provider in KEYWORD_RERANKER_PROVIDERS:
                return self._keyword_rerank(query, documents, limit)
            return documents[:limit]
        if provider in CROSS_ENCODER_RERANKER_PROVIDERS:
            return self._cross_encoder_rerank(query, documents, limit)
        if provider in COHERE_RERANKER_PROVIDERS:
            return self._cohere_rerank(query, documents, limit)
        if provider in LLM_RERANKER_PROVIDERS:
            return self._llm_rerank(query, documents, limit)
        self.last_status = self.status()
        return documents[:limit]

    def available(self) -> bool:
        return bool(self.status()["available"])

    def status(self) -> dict:
        provider = self._provider_key()
        return self._status_for_provider(provider, model_checked=True)

    def _auto_rerank(
        self,
        query: str,
        documents: list[NewsDocument],
        n_results: int,
    ) -> list[NewsDocument]:
        candidate_statuses = []
        cross_status = self._status_for_provider("bge", model_checked=True)
        candidate_statuses.append(cross_status)
        if cross_status.get("model_reranker_ready"):
            result = self._cross_encoder_rerank(query, documents, n_results, status_provider="bge")
            candidate_statuses[-1] = self.last_status
            if self.last_status.get("model_reranker_ready"):
                self.last_status = self._auto_status_from_result(
                    self.last_status,
                    candidate_statuses=candidate_statuses,
                )
                return result

        cohere_status = self._status_for_provider("cohere", model_checked=True)
        candidate_statuses.append(cohere_status)
        if cohere_status.get("model_reranker_ready"):
            result = self._cohere_rerank(query, documents, n_results, status_provider="cohere")
            candidate_statuses[-1] = self.last_status
            if self.last_status.get("model_reranker_ready"):
                self.last_status = self._auto_status_from_result(
                    self.last_status,
                    candidate_statuses=candidate_statuses,
                )
                return result

        llm_status = self._status_for_provider("llm", model_checked=True)
        candidate_statuses.append(llm_status)
        if llm_status.get("model_reranker_ready") and not self._llm_disabled_for_session:
            result = self._llm_rerank(query, documents, n_results, status_provider="llm")
            candidate_statuses[-1] = self.last_status
            if self.last_status.get("model_reranker_ready"):
                self.last_status = self._auto_status_from_result(
                    self.last_status,
                    candidate_statuses=candidate_statuses,
                )
                return result

        result = self._keyword_rerank(query, documents, n_results)
        keyword_status = self._status_for_provider("keyword", model_checked=False)
        self.last_status = self._auto_status_from_result(
            keyword_status,
            candidate_statuses=[*candidate_statuses, keyword_status],
        )
        return result

    def _cross_encoder_rerank(
        self,
        query: str,
        documents: list[NewsDocument],
        n_results: int,
        *,
        status_provider: str | None = None,
    ) -> list[NewsDocument]:
        provider = status_provider or self._provider_key()
        try:
            model = self._run_external("cross_encoder_model_load", self._cross_encoder_model)
        except RagOperationTimeout:
            self.last_status = self._timeout_status(provider, "cross_encoder_model_load", model=None)
            return documents[:n_results]
        if model is None:
            self.last_status = self._status_for_provider(
                provider,
                model_checked=True,
                model=None,
            )
            return documents[:n_results]
        pairs = [(query, self._document_text(document)) for document in documents]
        try:
            scores = self._run_external("cross_encoder_predict", lambda: list(model.predict(pairs)))
        except RagOperationTimeout:
            self.last_status = self._timeout_status(provider, "cross_encoder_predict", model=model)
            return documents[:n_results]
        except Exception as exc:
            self.last_status = self._status_for_provider(
                provider,
                model_checked=True,
                model=model,
                prediction_error=exc.__class__.__name__,
            )
            return documents[:n_results]
        indexed = list(enumerate(documents))
        indexed.sort(
            key=lambda item: (
                float(scores[item[0]]) if item[0] < len(scores) else float("-inf"),
                item[1].source.published_at or "",
                item[1].title,
            ),
            reverse=True,
        )
        self.last_status = self._status_for_provider(
            provider,
            model_checked=True,
            model=model,
        )
        return [document for _index, document in indexed[:n_results]]

    def _cohere_rerank(
        self,
        query: str,
        documents: list[NewsDocument],
        n_results: int,
        *,
        status_provider: str | None = None,
    ) -> list[NewsDocument]:
        provider = status_provider or self._provider_key()
        client = self._cohere_client()
        if client is None:
            self.last_status = self._status_for_provider(
                provider,
                model_checked=True,
                model=None,
            )
            return documents[:n_results]
        try:
            response = self._run_external(
                "cohere_rerank",
                lambda: client.rerank(
                    model=self._cohere_model_name(),
                    query=query,
                    documents=[self._document_text(document) for document in documents],
                    top_n=min(n_results, len(documents)),
                ),
            )
            reranked = self._documents_from_cohere_response(response, documents)
            if not reranked:
                self.last_status = self._status_for_provider(
                    provider,
                    model_checked=True,
                    model=client,
                    prediction_error="empty_response",
                )
                return documents[:n_results]
        except RagOperationTimeout:
            self.last_status = self._timeout_status(provider, "cohere_rerank", model=client)
            return documents[:n_results]
        except Exception as exc:
            self.last_status = self._status_for_provider(
                provider,
                model_checked=True,
                model=client,
                prediction_error=exc.__class__.__name__,
            )
            return documents[:n_results]
        self.last_status = self._status_for_provider(
            provider,
            model_checked=True,
            model=client,
        )
        return reranked[:n_results]

    def _llm_rerank(
        self,
        query: str,
        documents: list[NewsDocument],
        n_results: int,
        *,
        status_provider: str | None = None,
    ) -> list[NewsDocument]:
        provider = status_provider or self._provider_key()
        client = self._llm_client()
        if client is None:
            self.last_status = self._status_for_provider(provider, model_checked=True, model=None)
            return self._keyword_rerank(query, documents, n_results)

        candidate_limit = min(len(documents), max(n_results, self.llm_reranker_max_documents))
        candidates = self._keyword_rerank(query, documents, candidate_limit)
        candidate_ids = {id(document) for document in candidates}
        remainder = [document for document in documents if id(document) not in candidate_ids]
        prompt = self._llm_rerank_prompt(query, candidates)
        try:
            result = self._run_external("llm_rerank", lambda: client.generate_with_metadata(prompt))
            if getattr(result, "fallback", False):
                raise RuntimeError("llm_fallback")
            indexes = self._parse_llm_ranked_indexes(str(getattr(result, "text", "") or ""), len(candidates))
            if not indexes:
                raise RuntimeError("empty_or_unparseable_response")
        except RagOperationTimeout:
            self._llm_disabled_for_session = True
            self.last_status = self._timeout_status(provider, "llm_rerank", model=client)
            return self._keyword_rerank(query, documents, n_results)
        except Exception as exc:
            self._llm_disabled_for_session = True
            self.last_status = self._status_for_provider(
                provider,
                model_checked=True,
                model=client,
                prediction_error=exc.__class__.__name__,
            )
            self.last_status["fallback_reason"] = "llm_reranker_failed_session_disabled"
            return self._keyword_rerank(query, documents, n_results)

        ordered = apply_llm_ranked_indexes(candidates, remainder, indexes, n_results)
        self.last_status = self._status_for_provider(provider, model_checked=True, model=client)
        model_name = getattr(result, "model", None)
        if model_name:
            self.last_status["model"] = str(model_name)
        self.last_status["llm_attempt_count"] = len(getattr(result, "attempts", ()) or ())
        return ordered

    def _run_external(self, operation: str, func: Callable[[], Any]) -> Any:
        return run_with_timeout(func, self.timeout_seconds, operation)

    def _timeout_status(self, provider: str, operation: str, *, model: Any = None) -> dict:
        status = self._status_for_provider(
            provider,
            model_checked=True,
            model=model,
            prediction_error="TimeoutError",
        )
        status["model_reranker_gap"] = f"timeout:{operation}"
        status["fallback_reason"] = f"timeout:{operation}"
        status["timeout_seconds"] = self.timeout_seconds
        return status

    def _keyword_rerank(
        self,
        query: str,
        documents: list[NewsDocument],
        n_results: int,
    ) -> list[NewsDocument]:
        return keyword_rerank(
            query,
            documents,
            n_results,
            text_limit=self.text_limit,
        )

    @classmethod
    def _keyword_score(
        cls,
        query_counter: Counter[str],
        exact_terms: list[str],
        *,
        title: str,
        text: str,
    ) -> float:
        return keyword_score(
            query_counter,
            exact_terms,
            title=title,
            text=text,
        )

    @staticmethod
    def _source_quality_adjustment(document: NewsDocument) -> float:
        return source_quality_adjustment(document)

    def _cross_encoder_model(self):
        if not self.model_name:
            return None
        if self.cross_encoder_factory is not None:
            try:
                return self.cross_encoder_factory(self.model_name)
            except Exception:
                return None
        return _cached_cross_encoder(self.model_name)

    def _cohere_client(self):
        if not self._cohere_model_name() or not self.cohere_api_key:
            return None
        if self.cohere_client_factory is not None:
            try:
                return self.cohere_client_factory(self.cohere_api_key)
            except Exception:
                return None
        return _cached_cohere_client(self.cohere_api_key)

    def _llm_client(self):
        if not self.llm_reranker_enabled:
            return None
        if self.llm_client_factory is not None:
            try:
                return self.llm_client_factory()
            except Exception:
                return None
        try:
            from app.services.llm_client import LLMClient

            return LLMClient()
        except Exception:
            return None

    @staticmethod
    def _documents_from_cohere_response(response: object, documents: list[NewsDocument]) -> list[NewsDocument]:
        raw_results = getattr(response, "results", None)
        if raw_results is None and isinstance(response, dict):
            raw_results = response.get("results")
        indexes: list[int] = []
        for result in raw_results or []:
            index = result.get("index") if isinstance(result, dict) else getattr(result, "index", None)
            try:
                index_value = int(index)
            except (TypeError, ValueError):
                continue
            if 0 <= index_value < len(documents):
                indexes.append(index_value)
        seen = set()
        ordered = []
        for index in indexes:
            if index in seen:
                continue
            seen.add(index)
            ordered.append(documents[index])
        return ordered

    def _document_text(self, document: NewsDocument) -> str:
        return document_text(document, self.text_limit)

    def _provider_key(self) -> str:
        return self.provider.lower().replace("-", "_")

    def _cohere_model_name(self) -> str:
        model_name = self.model_name.strip()
        if self._provider_key() in AUTO_RERANKER_PROVIDERS and (
            not model_name or model_name.lower().startswith(("baai/", "bge"))
        ):
            return "rerank-v3.5"
        return model_name

    def _status_builder(self) -> RerankerStatusBuilder:
        return RerankerStatusBuilder(
            configured_provider=self.provider,
            normalized_provider=self._provider_key(),
            model_name=self.model_name,
            cohere_model_name=self._cohere_model_name(),
            cohere_api_key=self.cohere_api_key,
            llm_reranker_enabled=self.llm_reranker_enabled,
            cross_encoder_factory_configured=self.cross_encoder_factory is not None,
            cohere_client_factory_configured=self.cohere_client_factory is not None,
            llm_client_factory_configured=self.llm_client_factory is not None,
            module_available=self._module_available,
            load_cross_encoder_model=lambda: self._run_external("cross_encoder_model_load", self._cross_encoder_model),
            load_cohere_client=self._cohere_client,
        )

    def _base_status(self, provider: str | None = None) -> dict:
        return self._status_builder().base_status(provider or self._provider_key())

    def _status_for_provider(
        self,
        provider: str,
        *,
        model_checked: bool,
        model: Any = _MODEL_NOT_PROVIDED,
        prediction_error: str | None = None,
    ) -> dict:
        return self._status_builder().status_for_provider(
            provider,
            model_checked=model_checked,
            model=model,
            prediction_error=prediction_error,
        )

    def _cohere_status(
        self,
        base: dict,
        *,
        model_checked: bool,
        model: Any = _MODEL_NOT_PROVIDED,
        prediction_error: str | None = None,
    ) -> dict:
        return self._status_builder().cohere_status(
            base,
            model_checked=model_checked,
            model=model,
            prediction_error=prediction_error,
        )

    def _auto_status(self, *, model_checked: bool) -> dict:
        return self._status_builder().auto_status(model_checked=model_checked)

    def _auto_status_from_result(self, result_status: dict, *, candidate_statuses: list[dict]) -> dict:
        return self._status_builder().auto_status_from_result(result_status, candidate_statuses=candidate_statuses)

    @staticmethod
    def _auto_candidate_summary(status: dict) -> dict:
        return auto_candidate_summary(status)

    def _llm_status(
        self,
        base: dict,
        *,
        model_checked: bool,
        model: Any = _MODEL_NOT_PROVIDED,
        prediction_error: str | None = None,
    ) -> dict:
        return self._status_builder().llm_status(
            base,
            model_checked=model_checked,
            model=model,
            prediction_error=prediction_error,
        )

    def _llm_rerank_prompt(self, query: str, documents: list[NewsDocument]) -> str:
        return llm_rerank_prompt(query, documents, text_limit=self.text_limit)

    @staticmethod
    def _parse_llm_ranked_indexes(text: str, document_count: int) -> list[int]:
        return parse_llm_ranked_indexes(text, document_count)

    @staticmethod
    def _module_available(module_name: str) -> bool:
        try:
            return find_spec(module_name) is not None
        except (ImportError, ValueError):
            return False

    @staticmethod
    def _exact_query_terms(query: str) -> list[str]:
        return exact_query_terms(query)

    @classmethod
    def _tokenize(cls, text: str) -> list[str]:
        return tokenize(text)

    @staticmethod
    def _is_confusing_entity_prefix_token(text: str, token: str, index: int) -> bool:
        return is_confusing_entity_prefix_token(text, token, index)


@lru_cache(maxsize=4)
def _cached_cross_encoder(model_name: str):
    try:
        from sentence_transformers import CrossEncoder

        return CrossEncoder(model_name)
    except Exception:
        return None


@lru_cache(maxsize=2)
def _cached_cohere_client(api_key: str):
    try:
        import cohere

        if hasattr(cohere, "ClientV2"):
            return cohere.ClientV2(api_key=api_key)
        if hasattr(cohere, "Client"):
            return cohere.Client(api_key)
    except Exception:
        return None
    return None
