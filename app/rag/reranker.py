from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import date
from functools import lru_cache
from importlib.util import find_spec
import json
import re
from typing import Any, Optional

from app.core.config import get_settings
from app.models.schemas import NewsDocument
from app.rag.timeouts import RagOperationTimeout, run_with_timeout
from app.services.entity_mapping import CONFUSING_ENTITY_PREFIXES, alias_matches_text
from app.services.source_quality import is_low_quality_investor_forum_document


TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_+.-]*|[\u4e00-\u9fff]+")
OFFICIAL_SOURCE_HINTS = (
    "公開資訊觀測站",
    "mops",
    "twse",
    "tpex",
    "investor",
    "ir.",
    "/ir",
    "annual report",
    "法說",
    "法人說明",
)
DISABLED_RERANKER_PROVIDERS = {"", "none", "disabled", "off"}
AUTO_RERANKER_PROVIDERS = {"auto", "model_auto", "auto_model"}
KEYWORD_RERANKER_PROVIDERS = {"keyword", "hybrid"}
CROSS_ENCODER_RERANKER_PROVIDERS = {
    "sentence_transformers",
    "sentence_transformer",
    "cross_encoder",
    "bge",
}
COHERE_RERANKER_PROVIDERS = {"cohere", "cohere_rerank", "cohere_reranker"}
LLM_RERANKER_PROVIDERS = {"llm", "llm_rerank", "llm_reranker"}
_MODEL_NOT_PROVIDED = object()


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

        seen = set()
        ordered: list[NewsDocument] = []
        for index in indexes:
            if index in seen:
                continue
            seen.add(index)
            ordered.append(candidates[index])
        ordered.extend(document for index, document in enumerate(candidates) if index not in seen)
        ordered.extend(remainder)
        self.last_status = self._status_for_provider(provider, model_checked=True, model=client)
        model_name = getattr(result, "model", None)
        if model_name:
            self.last_status["model"] = str(model_name)
        self.last_status["llm_attempt_count"] = len(getattr(result, "attempts", ()) or ())
        return ordered[:n_results]

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
        query_terms = self._tokenize(query)
        exact_terms = self._exact_query_terms(query)
        if not query_terms and not exact_terms:
            return documents[:n_results]
        query_counter = Counter(query_terms)
        ranked = []
        for index, document in enumerate(documents):
            text = self._document_text(document)
            title = document.title or ""
            score = self._keyword_score(
                query_counter,
                exact_terms,
                title=title,
                text=text,
            )
            score += self._source_quality_adjustment(document)
            recency = document.source.published_at if score > 0 and document.source.published_at else date.min
            ranked.append((score, recency, -index, document))
        ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        return [document for _score, _recency, _index, document in ranked[:n_results]]

    @classmethod
    def _keyword_score(
        cls,
        query_counter: Counter[str],
        exact_terms: list[str],
        *,
        title: str,
        text: str,
    ) -> float:
        title_lower = title.lower()
        text_lower = text.lower()
        document_terms = Counter(cls._tokenize(f"{title}\n{text}"))
        score = 0.0
        for term, query_count in query_counter.items():
            frequency = document_terms.get(term, 0)
            if frequency <= 0:
                continue
            score += min(3, frequency) * query_count

        for term in exact_terms:
            term_lower = term.lower()
            if alias_matches_text(title_lower, term_lower):
                score += 4.0 if term_lower.isdigit() else 2.5
            if alias_matches_text(text_lower, term_lower):
                score += 2.0 if term_lower.isdigit() else 1.0
        return score

    @staticmethod
    def _source_quality_adjustment(document: NewsDocument) -> float:
        if is_low_quality_investor_forum_document(document):
            return -100.0
        haystack = " ".join(
            str(part or "")
            for part in (
                document.title,
                document.source.title,
                document.source.publisher,
                document.source.url,
            )
        ).lower()
        return 1.5 if any(hint.lower() in haystack for hint in OFFICIAL_SOURCE_HINTS) else 0.0

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
        text = f"{document.title}\n{document.text}"
        if self.text_limit <= 0:
            return text
        return text[: self.text_limit]

    def _provider_key(self) -> str:
        return self.provider.lower().replace("-", "_")

    def _cohere_model_name(self) -> str:
        model_name = self.model_name.strip()
        if self._provider_key() in AUTO_RERANKER_PROVIDERS and (
            not model_name or model_name.lower().startswith(("baai/", "bge"))
        ):
            return "rerank-v3.5"
        return model_name

    def _base_status(self, provider: str | None = None) -> dict:
        provider = provider or self._provider_key()
        return {
            "provider": provider,
            "normalized_provider": provider,
            "model": self.model_name,
            "available": False,
            "execution_mode": "input_order",
            "quality_tier": "none",
            "is_model_reranker": False,
            "model_reranker_ready": False,
            "keyword_fallback": False,
            "dependency": None,
            "dependency_available": None,
            "api_key_required": False,
            "api_key_configured": None,
            "model_checked": False,
            "model_available": None,
            "model_reranker_gap": None,
            "fallback_reason": None,
        }

    def _status_for_provider(
        self,
        provider: str,
        *,
        model_checked: bool,
        model: Any = _MODEL_NOT_PROVIDED,
        prediction_error: str | None = None,
    ) -> dict:
        base = self._base_status(provider)
        if provider in DISABLED_RERANKER_PROVIDERS:
            return {
                **base,
                "execution_mode": "input_order",
                "model_reranker_gap": "reranker_disabled",
                "fallback_reason": "reranker_disabled",
            }
        if provider in AUTO_RERANKER_PROVIDERS:
            return self._auto_status(model_checked=model_checked)
        if provider in KEYWORD_RERANKER_PROVIDERS:
            return {
                **base,
                "available": True,
                "execution_mode": "keyword",
                "quality_tier": "lexical_fallback",
                "keyword_fallback": True,
                "model_checked": False,
                "model_reranker_gap": "keyword_provider_selected",
                "fallback_reason": None,
            }
        if provider not in CROSS_ENCODER_RERANKER_PROVIDERS:
            if provider in COHERE_RERANKER_PROVIDERS:
                return self._cohere_status(
                    base,
                    model_checked=model_checked,
                    model=model,
                    prediction_error=prediction_error,
                )
            if provider in LLM_RERANKER_PROVIDERS:
                return self._llm_status(
                    base,
                    model_checked=model_checked,
                    model=model,
                    prediction_error=prediction_error,
                )
            return {
                **base,
                "execution_mode": "input_order",
                "model_reranker_gap": f"unsupported_provider:{provider}",
                "fallback_reason": f"unsupported_provider:{provider}",
            }

        dependency = "sentence_transformers"
        dependency_available = True if self.cross_encoder_factory is not None else self._module_available(dependency)
        fallback_reason = None
        model_available = None
        if not self.model_name:
            fallback_reason = "missing_model"
            model_available = False if model_checked else None
        elif not dependency_available:
            fallback_reason = f"missing_dependency:{dependency}"
            model_available = False if model_checked else None
        elif model_checked:
            if model is _MODEL_NOT_PROVIDED:
                try:
                    model = self._run_external("cross_encoder_model_load", self._cross_encoder_model)
                except RagOperationTimeout:
                    model = None
                    fallback_reason = "timeout:cross_encoder_model_load"
            model_available = model is not None
            if model is None and fallback_reason is None:
                fallback_reason = "model_unavailable"
        if prediction_error:
            fallback_reason = f"prediction_failed:{prediction_error}"
            model_available = model is not None

        available = fallback_reason is None
        return {
            **base,
            "available": available,
            "execution_mode": "cross_encoder" if available else "input_order_fallback",
            "quality_tier": "model_reranker" if available else "model_reranker_unavailable",
            "is_model_reranker": True,
            "model_reranker_ready": available,
            "dependency": dependency,
            "dependency_available": dependency_available,
            "model_checked": model_checked,
            "model_available": model_available,
            "model_reranker_gap": None if available else fallback_reason,
            "fallback_reason": fallback_reason,
        }

    def _cohere_status(
        self,
        base: dict,
        *,
        model_checked: bool,
        model: Any = _MODEL_NOT_PROVIDED,
        prediction_error: str | None = None,
    ) -> dict:
        dependency = "cohere"
        dependency_available = True if self.cohere_client_factory is not None else self._module_available(dependency)
        api_key_configured = bool(self.cohere_api_key)
        cohere_model_name = self._cohere_model_name()
        fallback_reason = None
        model_available = None
        if not cohere_model_name:
            fallback_reason = "missing_model"
            model_available = False if model_checked else None
        elif not api_key_configured:
            fallback_reason = "missing_api_key"
            model_available = False if model_checked else None
        elif not dependency_available:
            fallback_reason = f"missing_dependency:{dependency}"
            model_available = False if model_checked else None
        elif model_checked:
            if model is _MODEL_NOT_PROVIDED:
                model = self._cohere_client()
            model_available = model is not None
            if model is None:
                fallback_reason = "client_unavailable"
        if prediction_error:
            fallback_reason = f"prediction_failed:{prediction_error}"
            model_available = model is not None

        available = fallback_reason is None
        return {
            **base,
            "model": cohere_model_name,
            "available": available,
            "execution_mode": "cohere_api" if available else "input_order_fallback",
            "quality_tier": "api_model_reranker" if available else "model_reranker_unavailable",
            "is_model_reranker": True,
            "model_reranker_ready": available,
            "dependency": dependency,
            "dependency_available": dependency_available,
            "api_key_required": True,
            "api_key_configured": api_key_configured,
            "model_checked": model_checked,
            "model_available": model_available,
            "model_reranker_gap": None if available else fallback_reason,
            "fallback_reason": fallback_reason,
        }

    def _auto_status(self, *, model_checked: bool) -> dict:
        cross_status = self._status_for_provider("bge", model_checked=model_checked)
        if cross_status.get("model_reranker_ready"):
            return self._auto_status_from_result(cross_status, candidate_statuses=[cross_status])

        cohere_status = self._status_for_provider("cohere", model_checked=model_checked)
        if cohere_status.get("model_reranker_ready"):
            return self._auto_status_from_result(
                cohere_status,
                candidate_statuses=[cross_status, cohere_status],
            )

        llm_status = self._status_for_provider("llm", model_checked=model_checked)
        if llm_status.get("model_reranker_ready"):
            return self._auto_status_from_result(
                llm_status,
                candidate_statuses=[cross_status, cohere_status, llm_status],
            )

        keyword_status = self._status_for_provider("keyword", model_checked=False)
        return self._auto_status_from_result(
            keyword_status,
            candidate_statuses=[cross_status, cohere_status, llm_status, keyword_status],
        )

    def _auto_status_from_result(self, result_status: dict, *, candidate_statuses: list[dict]) -> dict:
        provider = self._provider_key()
        selected = str(result_status.get("normalized_provider") or result_status.get("provider") or "")
        model_gap = result_status.get("model_reranker_gap")
        if selected in KEYWORD_RERANKER_PROVIDERS:
            model_gap = "auto_model_reranker_unavailable:" + ";".join(
                str(status.get("model_reranker_gap") or status.get("fallback_reason") or "not_ready")
                for status in candidate_statuses
                if status.get("is_model_reranker")
            )
        return {
            **result_status,
            "provider": self.provider,
            "normalized_provider": provider,
            "configured_provider": self.provider,
            "resolved_provider": selected,
            "auto_candidates": [self._auto_candidate_summary(status) for status in candidate_statuses],
            "model_reranker_gap": model_gap,
        }

    @staticmethod
    def _auto_candidate_summary(status: dict) -> dict:
        return {
            "provider": status.get("normalized_provider") or status.get("provider"),
            "execution_mode": status.get("execution_mode"),
            "quality_tier": status.get("quality_tier"),
            "model": status.get("model"),
            "model_reranker_ready": status.get("model_reranker_ready"),
            "dependency_available": status.get("dependency_available"),
            "api_key_configured": status.get("api_key_configured"),
            "model_available": status.get("model_available"),
            "fallback_reason": status.get("fallback_reason"),
        }

    def _llm_status(
        self,
        base: dict,
        *,
        model_checked: bool,
        model: Any = _MODEL_NOT_PROVIDED,
        prediction_error: str | None = None,
    ) -> dict:
        settings = get_settings()
        provider = str(getattr(settings, "llm_provider", "gemini_http") or "gemini_http").lower().replace("-", "_")
        dependency = "litellm" if provider == "litellm" else "google.genai" if provider == "google_genai" else None
        dependency_available = (
            None
            if dependency is None
            else True
            if self.llm_client_factory is not None
            else self._module_available(dependency)
        )
        api_key_configured = bool(
            self.llm_client_factory is not None
            or getattr(settings, "gemini_api_keys", [])
            or getattr(settings, "openai_api_key", None)
            or getattr(settings, "anthropic_api_key", None)
        )
        fallback_reason = None
        model_available = None
        if not self.llm_reranker_enabled:
            fallback_reason = "llm_reranker_disabled"
            model_available = False if model_checked else None
        elif dependency_available is False and not getattr(settings, "gemini_api_keys", []):
            fallback_reason = f"missing_dependency:{dependency}"
            model_available = False if model_checked else None
        elif not api_key_configured:
            fallback_reason = "missing_api_key"
            model_available = False if model_checked else None
        elif model_checked:
            if model is _MODEL_NOT_PROVIDED:
                model = True
            model_available = model is not None
            if model is None:
                fallback_reason = "client_unavailable"
        if prediction_error:
            fallback_reason = f"prediction_failed:{prediction_error}"
            model_available = model is not None

        available = fallback_reason is None
        return {
            **base,
            "model": str(getattr(settings, "primary_llm_model", "") or "llm"),
            "available": available,
            "execution_mode": "llm_rerank" if available else "input_order_fallback",
            "quality_tier": "llm_model_reranker" if available else "model_reranker_unavailable",
            "is_model_reranker": True,
            "model_reranker_ready": available,
            "dependency": dependency,
            "dependency_available": dependency_available,
            "api_key_required": True,
            "api_key_configured": api_key_configured,
            "model_checked": model_checked,
            "model_available": model_available,
            "model_reranker_gap": None if available else fallback_reason,
            "fallback_reason": fallback_reason,
        }

    def _llm_rerank_prompt(self, query: str, documents: list[NewsDocument]) -> str:
        rows = []
        for index, document in enumerate(documents):
            source = document.source
            rows.append(
                {
                    "index": index,
                    "title": document.title,
                    "publisher": source.publisher,
                    "date": source.published_at.isoformat() if source.published_at else None,
                    "text": self._document_text(document),
                }
            )
        return (
            "你是 RAG 檢索重排序器。請依照查詢與文件內容的直接相關性、公司/股票代號精準命中、"
            "來源品質與日期新鮮度，將文件由最相關排到最不相關。\n"
            "只輸出 JSON 陣列，內容是文件 index，例如 [2,0,1]；不要輸出解釋文字。\n"
            f"查詢：{query}\n"
            f"文件：{json.dumps(rows, ensure_ascii=False)}"
        )

    @staticmethod
    def _parse_llm_ranked_indexes(text: str, document_count: int) -> list[int]:
        match = re.search(r"\[[\s\d,]+\]", str(text or ""))
        if not match:
            return []
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []
        indexes: list[int] = []
        for value in parsed:
            try:
                index = int(value)
            except (TypeError, ValueError):
                continue
            if 0 <= index < document_count:
                indexes.append(index)
        return indexes

    @staticmethod
    def _module_available(module_name: str) -> bool:
        try:
            return find_spec(module_name) is not None
        except (ImportError, ValueError):
            return False

    @staticmethod
    def _exact_query_terms(query: str) -> list[str]:
        terms = []
        seen = set()
        for raw_term in str(query or "").split():
            term = raw_term.strip()
            if len(term) < 2:
                continue
            key = term.lower()
            if key in seen:
                continue
            seen.add(key)
            terms.append(term)
        return terms

    @classmethod
    def _tokenize(cls, text: str) -> list[str]:
        tokens: list[str] = []
        for match in TOKEN_RE.findall(str(text or "").lower()):
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
