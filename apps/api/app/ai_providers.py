"""JSON generation over four operator-configured, server-only provider protocols."""
import asyncio
from dataclasses import dataclass, field
import json
import os
from urllib.parse import quote, urlsplit

import httpx


PROVIDERS = {
    "openai": ("OPENAI", "https://api.openai.com/v1"),
    "anthropic": ("ANTHROPIC", "https://api.anthropic.com/v1"),
    "gemini": ("GEMINI", "https://generativelanguage.googleapis.com/v1beta"),
    "ollama": ("OLLAMA", ""),
}
RESPONSE_LIMIT = 256 * 1024


class ProviderError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Connection:
    provider: str
    base: str = field(repr=False)
    headers: dict = field(repr=False)
    input_rate: int | None = None
    output_rate: int | None = None


def configured_connection(provider):
    suffix, default = PROVIDERS[provider]
    prefix = f"VYRNEXIS_AI_{suffix}"
    raw = os.getenv(f"{prefix}_URL", default).rstrip("/")
    token = os.getenv(f"{prefix}_KEY", "")
    try:
        url = urlsplit(raw)
        _ = url.port
    except ValueError:
        return None
    if (not url.hostname or url.username or url.password or url.query or url.fragment
            or url.scheme not in ({"http", "https"} if provider == "ollama" else {"https"})):
        return None
    if provider == "ollama" and url.hostname not in {"localhost", "127.0.0.1", "::1", "host.docker.internal", "ollama"}:
        return None
    if provider != "ollama" and not token:
        return None
    headers = {
        "openai": {"Authorization": f"Bearer {token}"},
        "anthropic": {"x-api-key": token, "anthropic-version": "2023-06-01"},
        "gemini": {"x-goog-api-key": token},
        "ollama": {"Authorization": f"Bearer {token}"} if token else {},
    }[provider]
    try:
        rates = tuple(int(os.getenv(f"{prefix}_{side}_MICROS_PER_1K", "")) for side in ("INPUT", "OUTPUT"))
        if not all(0 <= value <= 1_000_000 for value in rates):
            rates = (None, None)
    except ValueError:
        rates = (None, None)
    return Connection(provider, raw, headers, *rates)


def request_shape(provider, model, prompt, limit):
    encoded_model = quote(model, safe="")
    if prompt is None:
        return ("POST", "/api/show", {"model": model, "verbose": False}) if provider == "ollama" else (
            "GET", f"/models/{encoded_model}", None,
        )
    system, context = prompt
    messages = [{"role": "system", "content": system}, {"role": "user", "content": context}]
    if provider == "anthropic":
        return "POST", "/messages", {"model": model, "system": system, "max_tokens": limit,
                                      "messages": messages[1:]}
    if provider == "gemini":
        return "POST", f"/models/{encoded_model}:generateContent", {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": context}]}],
            "generationConfig": {"maxOutputTokens": limit, "responseMimeType": "application/json"},
        }
    if provider == "ollama":
        return "POST", "/api/chat", {
            "model": model, "messages": messages, "format": "json", "stream": False,
            "options": {"num_predict": limit},
        }
    return "POST", "/chat/completions", {
        "model": model, "messages": messages, "max_completion_tokens": limit,
        "response_format": {"type": "json_object"}, "stream": False,
    }


def read_answer(provider, payload):
    try:
        if provider == "anthropic":
            content = "".join(part["text"] for part in payload["content"] if part["type"] == "text")
            return json.loads(content), payload["usage"].get("input_tokens"), payload["usage"].get("output_tokens")
        if provider == "gemini":
            parts = payload["candidates"][0]["content"]["parts"]
            content = "".join(part["text"] for part in parts if "text" in part and not part.get("thought"))
            usage = payload.get("usageMetadata", {})
            output = usage.get("candidatesTokenCount")
            if type(output) is int:
                output += usage.get("thoughtsTokenCount", 0)
            return json.loads(content), usage.get("promptTokenCount"), output
        if provider == "ollama":
            return json.loads(payload["message"]["content"]), payload.get("prompt_eval_count"), payload.get("eval_count")
        usage = payload.get("usage", {})
        return json.loads(payload["choices"][0]["message"]["content"]), usage.get("prompt_tokens"), usage.get("completion_tokens")
    except (AttributeError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise ProviderError("invalid_response") from exc


async def request_provider(connection, model, *, timeout, prompt=None, limit=0, transport=None):
    method, path, body = request_shape(connection.provider, model, prompt, limit)
    try:
        async with asyncio.timeout(timeout):
            async with httpx.AsyncClient(
                timeout=timeout, follow_redirects=False, trust_env=False, transport=transport,
            ) as client:
                for attempt in range(2):
                    try:
                        async with client.stream(method, connection.base + path, headers=connection.headers, json=body) as response:
                            if response.status_code == 429 and attempt == 0:
                                await asyncio.sleep(0.35)
                                continue
                            if not response.is_success:
                                code = {401: "credentials_rejected", 403: "access_denied",
                                        404: "model_unavailable", 429: "rate_limited"}.get(response.status_code)
                                raise ProviderError(code or "provider_error")
                            data = bytearray()
                            async for part in response.aiter_bytes(chunk_size=65536):
                                data.extend(part)
                                if len(data) > RESPONSE_LIMIT:
                                    raise ProviderError("response_limit")
                            decoded = json.loads(data)
                            if not isinstance(decoded, dict):
                                raise ProviderError("invalid_response")
                            return {"status": "connected"} if prompt is None else read_answer(connection.provider, decoded)
                    except (httpx.ConnectTimeout, httpx.ConnectError):
                        if attempt:
                            raise
                        await asyncio.sleep(0.35)
    except (TimeoutError, httpx.TimeoutException) as exc:
        raise ProviderError("timeout") from exc
    except httpx.RequestError as exc:
        raise ProviderError("unreachable") from exc
    except (UnicodeError, ValueError) as exc:
        raise ProviderError("invalid_response") from exc
