from __future__ import annotations

from importlib import import_module
from typing import Any

from app.services.llm_provider_calls import (
    call_gemini as _call_gemini_provider,
    call_gemini_vision as _call_gemini_vision_provider,
    call_google_genai as _call_google_genai_provider,
    call_litellm as _call_litellm_provider,
    call_litellm_vision as _call_litellm_vision_provider,
    google_genai_response_text as _google_genai_response_text_provider,
    image_data_url as _image_data_url_provider,
    normalize_vision_images as _normalize_vision_images_provider,
    tool_call_arguments as _tool_call_arguments_provider,
)
from app.services.llm_runtime import exception_status_code as _exception_status_code


class LLMProviderCallMixin:
    @staticmethod
    def _import_module(name: str) -> object:
        return import_module(name)

    @staticmethod
    def _exception_status_code(exc: Exception) -> int | None:
        return _exception_status_code(exc)

    def _call_litellm(
        self,
        prompt: str,
        model: str,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: dict[str, Any] | str | None = None,
    ) -> str:
        return _call_litellm_provider(
            prompt,
            model,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            tools=tools,
            tool_choice=tool_choice,
            import_module_func=self._import_module,
        )

    def _call_litellm_vision(
        self,
        prompt: str,
        *,
        images: list[dict[str, str]],
        model: str,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
    ) -> str:
        return _call_litellm_vision_provider(
            prompt,
            images=images,
            model=model,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            import_module_func=self._import_module,
        )

    @staticmethod
    def _tool_call_arguments(message: object) -> str:
        return _tool_call_arguments_provider(message)

    def _call_google_genai(
        self,
        prompt: str,
        api_key: str,
        *,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> str:
        return _call_google_genai_provider(
            prompt,
            api_key,
            model=model,
            primary_model=self.settings.primary_llm_model,
            timeout_seconds=timeout_seconds,
            import_module_func=self._import_module,
        )

    @staticmethod
    def _google_genai_response_text(response: object) -> str:
        return _google_genai_response_text_provider(response)

    def _call_gemini(
        self,
        prompt: str,
        api_key: str,
        *,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> str:
        return _call_gemini_provider(
            prompt,
            api_key,
            model=model,
            primary_model=self.settings.primary_llm_model,
            timeout_seconds=timeout_seconds,
        )

    def _call_gemini_vision(
        self,
        prompt: str,
        *,
        images: list[dict[str, str]],
        api_key: str,
        model: str,
        timeout_seconds: float | None = None,
    ) -> str:
        return _call_gemini_vision_provider(
            prompt,
            images=images,
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
        )

    @staticmethod
    def _normalize_vision_images(images: list[dict[str, Any]]) -> list[dict[str, str]]:
        return _normalize_vision_images_provider(images)

    @staticmethod
    def _image_data_url(image: dict[str, str]) -> str:
        return _image_data_url_provider(image)


__all__ = ["LLMProviderCallMixin"]
