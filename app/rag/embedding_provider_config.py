from __future__ import annotations

import re
from hashlib import sha1
from importlib.util import find_spec
from typing import Any, Callable

from app.core.config import get_settings
from app.rag.embedding_functions import GoogleGenAIEmbeddingFunction

CHROMA_DEFAULT_PROVIDER_ALIASES = {"", "default", "chroma", "chroma_default", "none"}


def normalized_embedding_provider(settings: Any) -> str:
    return str(settings.rag_embedding_provider or "chroma_default").lower().replace("-", "_")


def embedding_provider_spec(provider: str) -> dict | None:
    if provider in {"sentence_transformers", "sentence_transformer", "multilingual_e5", "e5"}:
        return {
            "factory_name": "SentenceTransformerEmbeddingFunction",
            "dependency": "sentence_transformers",
            "api_key_required": False,
        }
    if provider == "openai":
        return {
            "factory_name": "OpenAIEmbeddingFunction",
            "dependency": "openai",
            "api_key_required": True,
        }
    if provider in {"google_genai", "google_sdk", "gemini_genai"}:
        return {
            "factory_name": "GoogleGenAIEmbeddingFunction",
            "dependency": "google.genai",
            "api_key_required": True,
            "local_factory": True,
        }
    if provider in {"google", "gemini"}:
        return {
            "factory_name": "GoogleGenerativeAiEmbeddingFunction",
            "dependency": "google.generativeai",
            "api_key_required": True,
        }
    return None


def embedding_factory(embedding_functions_module: Any | None, spec: dict) -> Any | None:
    if spec.get("local_factory") and spec.get("factory_name") == "GoogleGenAIEmbeddingFunction":
        return GoogleGenAIEmbeddingFunction
    return (
        getattr(embedding_functions_module, spec["factory_name"], None)
        if embedding_functions_module and spec.get("factory_name")
        else None
    )


def embedding_dependency_available(
    dependency: str | None,
    dependency_checker: Callable[[str], bool] | None = None,
) -> bool | None:
    if not dependency:
        return None
    checker = dependency_checker or (lambda module_name: find_spec(module_name) is not None)
    try:
        return bool(checker(dependency))
    except Exception:
        return False


def embedding_api_key(settings: Any, provider: str) -> str | None:
    if provider == "openai":
        return getattr(settings, "openai_api_key", None)
    if provider in {"google", "gemini", "google_genai", "google_sdk", "gemini_genai"}:
        google_key = getattr(settings, "google_api_key", None)
        if google_key:
            return google_key
        gemini_keys = getattr(settings, "gemini_api_keys", [])
        return gemini_keys[0] if gemini_keys else None
    return None


def embedding_provider_status(
    settings: Any | None = None,
    embedding_functions_module: Any | None = None,
    dependency_checker: Callable[[str], bool] | None = None,
) -> dict:
    settings = settings or get_settings()
    provider = normalized_embedding_provider(settings)
    model_name = str(settings.rag_embedding_model or "").strip()
    default_status = {
        "provider": str(settings.rag_embedding_provider or ""),
        "normalized_provider": provider,
        "model": model_name,
        "custom_embedding_requested": provider not in CHROMA_DEFAULT_PROVIDER_ALIASES,
        "custom_embedding_enabled": False,
        "factory_name": None,
        "factory_available": False,
        "dependency": None,
        "dependency_available": None,
        "api_key_required": False,
        "api_key_configured": None,
        "chroma_default_fallback_allowed": bool(
            getattr(settings, "rag_allow_chroma_default_embedding_fallback", False)
        ),
        "fallback_reason": None,
    }
    if not default_status["custom_embedding_requested"]:
        return {**default_status, "fallback_reason": "chroma_default_requested"}

    spec = embedding_provider_spec(provider)
    if spec is None:
        return {**default_status, "fallback_reason": f"unsupported_provider:{provider}"}

    factory = embedding_factory(embedding_functions_module, spec)
    dependency_available = embedding_dependency_available(
        spec["dependency"],
        dependency_checker,
    )
    api_key_configured = True
    if spec["api_key_required"]:
        api_key_configured = bool(embedding_api_key(settings, provider))

    fallback_reason = None
    if not model_name:
        fallback_reason = "missing_model"
    elif embedding_functions_module is None and not spec.get("local_factory"):
        fallback_reason = "chromadb_embedding_functions_unavailable"
    elif factory is None:
        fallback_reason = f"factory_unavailable:{spec['factory_name']}"
    elif dependency_available is False:
        fallback_reason = f"missing_dependency:{spec['dependency']}"
    elif not api_key_configured:
        fallback_reason = "missing_api_key"

    custom_embedding_enabled = fallback_reason is None
    return {
        **default_status,
        "custom_embedding_enabled": custom_embedding_enabled,
        "factory_name": spec["factory_name"],
        "factory_available": factory is not None,
        "dependency": spec["dependency"],
        "dependency_available": dependency_available,
        "api_key_required": spec["api_key_required"],
        "api_key_configured": api_key_configured,
        "fallback_reason": fallback_reason,
    }


def build_embedding_function(
    settings: Any,
    embedding_functions_module: Any,
    dependency_checker: Callable[[str], bool] | None = None,
):
    status = embedding_provider_status(
        settings=settings,
        embedding_functions_module=embedding_functions_module,
        dependency_checker=dependency_checker,
    )
    if not status["custom_embedding_enabled"]:
        return None
    provider = status["normalized_provider"]
    model_name = str(settings.rag_embedding_model or "").strip()
    spec = embedding_provider_spec(provider) or {}
    factory = embedding_factory(embedding_functions_module, spec)
    if factory is None:
        return None
    try:
        if provider in {"sentence_transformers", "sentence_transformer", "multilingual_e5", "e5"}:
            return factory(model_name=model_name)
        if provider == "openai":
            return factory(api_key=embedding_api_key(settings, provider), model_name=model_name)
        if provider in {"google_genai", "google_sdk", "gemini_genai"}:
            return factory(
                api_key=embedding_api_key(settings, provider),
                model_name=model_name,
                output_dimensionality=getattr(settings, "rag_embedding_output_dimensionality", None),
            )
        if provider in {"google", "gemini"}:
            return factory(api_key=embedding_api_key(settings, provider), model_name=model_name)
    except Exception:
        return None
    return None


def collection_name_for_settings(
    collection_name: str,
    settings: Any,
    embedding_function_available: bool = True,
) -> str:
    provider = str(getattr(settings, "rag_embedding_provider", "") or "chroma_default").lower()
    provider = provider.replace("-", "_")
    model = str(getattr(settings, "rag_embedding_model", "") or "default").lower()
    schema_version = index_schema_version(settings)
    if (
        not embedding_function_available
        or provider in CHROMA_DEFAULT_PROVIDER_ALIASES
    ):
        provider = "chroma_default"
        model = "default"
    digest = sha1(f"{provider}|{model}|{schema_version}".encode("utf-8")).hexdigest()[:10]
    base = collection_name_part(collection_name, 24)
    provider_label = collection_name_part(provider or "chroma_default", 18)
    schema_label = collection_name_part(schema_version, 16)
    return f"{base}_{provider_label}_{schema_label}_{digest}"[:63]


def index_schema_version(settings: Any) -> str:
    version = str(getattr(settings, "rag_index_schema_version", "") or "").strip()
    return version or "identity-v2"


def collection_name_part(value: str, max_length: int) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", str(value).lower()).strip("_")
    return (normalized or "default")[:max(1, max_length)]
