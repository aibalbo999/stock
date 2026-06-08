from __future__ import annotations

import base64
from collections.abc import Callable
from importlib import import_module as default_import_module
from typing import Any

import httpx

from app.services.llm_models import gemini_api_model_name

ImportModuleFunc = Callable[[str], Any]


def call_litellm(
    prompt: str,
    model: str,
    api_key: str | None = None,
    timeout_seconds: float | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: dict[str, Any] | str | None = None,
    *,
    import_module_func: ImportModuleFunc = default_import_module,
) -> str:
    litellm = import_module_func("litellm")
    try:
        litellm.suppress_debug_info = True
    except Exception:
        pass
    kwargs = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "top_p": 0.8,
        "max_tokens": 8192,
        "timeout": min(20.0, timeout_seconds or 20.0),
    }
    if api_key:
        kwargs["api_key"] = api_key
    if tools:
        kwargs["tools"] = tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice
    response = litellm.completion(**kwargs)
    if isinstance(response, dict):
        choice = (response.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        tool_arguments = tool_call_arguments(message)
        if tool_arguments:
            return tool_arguments
        return str(message.get("content") or "").strip()
    choice = response.choices[0]
    tool_arguments = tool_call_arguments(choice.message)
    if tool_arguments:
        return tool_arguments
    return str(choice.message.content or "").strip()


def call_litellm_vision(
    prompt: str,
    *,
    images: list[dict[str, str]],
    model: str,
    api_key: str | None = None,
    timeout_seconds: float | None = None,
    import_module_func: ImportModuleFunc = default_import_module,
) -> str:
    litellm = import_module_func("litellm")
    try:
        litellm.suppress_debug_info = True
    except Exception:
        pass
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    content.extend(
        {
            "type": "image_url",
            "image_url": {"url": image_data_url(image)},
        }
        for image in images
    )
    kwargs = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.1,
        "top_p": 0.8,
        "max_tokens": 8192,
        "timeout": min(45.0, timeout_seconds or 45.0),
    }
    if api_key:
        kwargs["api_key"] = api_key
    response = litellm.completion(**kwargs)
    if isinstance(response, dict):
        choice = (response.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        return str(message.get("content") or "").strip()
    return str(response.choices[0].message.content or "").strip()


def tool_call_arguments(message: object) -> str:
    tool_calls = (
        message.get("tool_calls")
        if isinstance(message, dict)
        else getattr(message, "tool_calls", None)
    ) or []
    if not tool_calls:
        return ""
    first_call = tool_calls[0]
    function = (
        first_call.get("function")
        if isinstance(first_call, dict)
        else getattr(first_call, "function", None)
    )
    arguments = (
        function.get("arguments")
        if isinstance(function, dict)
        else getattr(function, "arguments", None)
    )
    return str(arguments or "").strip()


def call_google_genai(
    prompt: str,
    api_key: str,
    *,
    model: str | None = None,
    primary_model: str,
    timeout_seconds: float | None = None,
    import_module_func: ImportModuleFunc = default_import_module,
) -> str:
    del timeout_seconds
    genai = import_module_func("google.genai")
    genai_types = import_module_func("google.genai.types")
    client = genai.Client(api_key=api_key)
    config = genai_types.GenerateContentConfig(
        temperature=0.2,
        top_p=0.8,
        max_output_tokens=8192,
    )
    response = client.models.generate_content(
        model=gemini_api_model_name(model or primary_model),
        contents=prompt,
        config=config,
    )
    return google_genai_response_text(response)


def google_genai_response_text(response: object) -> str:
    text = getattr(response, "text", None)
    if text:
        return str(text).strip()
    if isinstance(response, dict):
        text = response.get("text")
        if text:
            return str(text).strip()
        candidates = response.get("candidates") or []
    else:
        candidates = getattr(response, "candidates", None) or []
    parts: list[str] = []
    for candidate in candidates:
        content = (
            candidate.get("content")
            if isinstance(candidate, dict)
            else getattr(candidate, "content", None)
        )
        candidate_parts = (
            content.get("parts") if isinstance(content, dict) else getattr(content, "parts", [])
        )
        for part in candidate_parts or []:
            part_text = part.get("text") if isinstance(part, dict) else getattr(part, "text", "")
            if part_text:
                parts.append(str(part_text))
    return "\n".join(parts).strip()


def call_gemini(
    prompt: str,
    api_key: str,
    *,
    model: str | None = None,
    primary_model: str,
    timeout_seconds: float | None = None,
) -> str:
    model_name = gemini_api_model_name(model or primary_model)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "topP": 0.8,
            "maxOutputTokens": 8192,
        },
    }
    with httpx.Client(timeout=min(45.0, timeout_seconds or 45.0)) as client:
        response = client.post(url, headers={"x-goog-api-key": api_key}, json=payload)
        response.raise_for_status()
    data = response.json()
    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    return "\n".join(part.get("text", "") for part in parts).strip()


def call_gemini_vision(
    prompt: str,
    *,
    images: list[dict[str, str]],
    api_key: str,
    model: str,
    timeout_seconds: float | None = None,
) -> str:
    model_name = gemini_api_model_name(model)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
    parts: list[dict[str, Any]] = [{"text": prompt}]
    parts.extend(
        {
            "inlineData": {
                "mimeType": image["mime_type"],
                "data": image["base64"],
            }
        }
        for image in images
    )
    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0.1,
            "topP": 0.8,
            "maxOutputTokens": 8192,
        },
    }
    with httpx.Client(timeout=min(45.0, timeout_seconds or 45.0)) as client:
        response = client.post(url, headers={"x-goog-api-key": api_key}, json=payload)
        response.raise_for_status()
    data = response.json()
    candidate_parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    return "\n".join(part.get("text", "") for part in candidate_parts).strip()


def normalize_vision_images(images: list[dict[str, Any]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for image in images or []:
        mime_type = str(image.get("mime_type") or image.get("mimeType") or "image/png")
        data = image.get("data")
        if isinstance(data, bytes):
            encoded = base64.b64encode(data).decode("ascii")
        else:
            encoded = str(image.get("base64") or data or "").strip()
        if not encoded:
            continue
        normalized.append({"mime_type": mime_type, "base64": encoded})
    return normalized


def image_data_url(image: dict[str, str]) -> str:
    return f"data:{image['mime_type']};base64,{image['base64']}"
