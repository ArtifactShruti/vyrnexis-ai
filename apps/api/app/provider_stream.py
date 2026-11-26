"""Read native provider streams and validate the complete structured answer."""
import asyncio
import codecs
import json
import re

import httpx

from .ai_providers import RESPONSE_LIMIT, ProviderError, request_shape


ANSWER_START = re.compile(r'(?:^\s*\{\s*|,\s*)"answer"\s*:\s*"')
STRING_PREFIX = re.compile(r'(?:[^"\\\x00-\x1f]|\\["\\/bfnrt]|\\u[0-9a-fA-F]{4})*')


def provisional_answer(text):
    match = ANSWER_START.search(text)
    if not match:
        return ""
    valid = STRING_PREFIX.match(text, match.end()).group()
    return json.loads('"' + valid + '"')[:5000]


def stream_event(provider, item):
    if provider == "ollama":
        return item.get("message", {}).get("content", ""), item.get("prompt_eval_count"), item.get("eval_count"), item.get("done") is True
    if provider == "anthropic":
        kind = item.get("type")
        if kind == "error":
            raise ProviderError("provider_error")
        if kind == "message_start":
            return "", item.get("message", {}).get("usage", {}).get("input_tokens"), None, False
        if kind == "message_delta":
            return "", None, item.get("usage", {}).get("output_tokens"), False
        return item.get("delta", {}).get("text", "") if kind == "content_block_delta" else "", None, None, kind == "message_stop"
    if provider == "gemini":
        usage = item.get("usageMetadata", {})
        candidates = item.get("candidates") or [{}]
        candidate = candidates[0]
        parts = candidate.get("content", {}).get("parts", [])
        text = "".join(part.get("text", "") for part in parts if not part.get("thought"))
        output = usage.get("candidatesTokenCount")
        if type(output) is int:
            output += usage.get("thoughtsTokenCount", 0)
        return text, usage.get("promptTokenCount"), output, bool(candidate.get("finishReason"))
    usage = item.get("usage") or {}
    choices = item.get("choices") or [{}]
    choice = choices[0]
    return choice.get("delta", {}).get("content") or "", usage.get("prompt_tokens"), usage.get("completion_tokens"), False


async def native_stream(connection, model, *, timeout, prompt, limit, on_partial, transport=None):
    provider = connection.provider
    _, path, body = request_shape(provider, model, prompt, limit)
    if provider == "gemini":
        path = path.replace(":generateContent", ":streamGenerateContent?alt=sse")
    else:
        body["stream"] = True
        if provider == "openai":
            body["stream_options"] = {"include_usage": True}
    text, partial, input_tokens, output_tokens, complete = "", "", None, None, False
    raw_size = 0
    decoder = codecs.getincrementaldecoder("utf-8")()
    buffer = ""
    try:
        async with asyncio.timeout(timeout):
            async with httpx.AsyncClient(
                timeout=timeout, follow_redirects=False, trust_env=False, transport=transport,
            ) as client:
                async with client.stream("POST", connection.base + path, headers=connection.headers, json=body) as response:
                    if not response.is_success:
                        code = {401: "credentials_rejected", 403: "access_denied", 404: "model_unavailable",
                                429: "rate_limited"}.get(response.status_code, "provider_error")
                        raise ProviderError(code)
                    async for data in response.aiter_bytes():
                        raw_size += len(data)
                        if raw_size > RESPONSE_LIMIT:
                            raise ProviderError("response_limit")
                        buffer += decoder.decode(data)
                        lines = buffer.split("\n")
                        buffer = lines.pop()
                        for line in lines:
                            line = line.strip()
                            if provider != "ollama":
                                if not line.startswith("data:"):
                                    continue
                                line = line[5:].strip()
                            if line == "[DONE]":
                                complete = True
                                continue
                            if not line:
                                continue
                            item = json.loads(line)
                            if item.get("error"):
                                raise ProviderError("provider_error")
                            delta, in_count, out_count, finished = stream_event(provider, item)
                            complete = complete or finished
                            input_tokens = in_count if in_count is not None else input_tokens
                            output_tokens = out_count if out_count is not None else output_tokens
                            if delta:
                                text += delta
                                verified_prefix = provisional_answer(text)
                                if verified_prefix and verified_prefix != partial:
                                    partial = verified_prefix
                                    await on_partial(partial)
        if not complete:
            raise ProviderError("stream_incomplete")
        return json.loads(text), input_tokens, output_tokens
    except (TimeoutError, httpx.TimeoutException) as exc:
        raise ProviderError("timeout") from exc
    except httpx.RequestError as exc:
        raise ProviderError("unreachable") from exc
    except (AttributeError, LookupError, TypeError, ValueError) as exc:
        raise ProviderError("invalid_response") from exc
