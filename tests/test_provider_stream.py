import asyncio
import json

import httpx
import pytest

from app.ai_providers import Connection, ProviderError
from app.provider_stream import native_stream
from test_ai_workspace import conversation, upload
from test_api import register


@pytest.mark.parametrize("provider", ["openai", "anthropic", "gemini", "ollama"])
def test_native_adapter_consumes_incremental_provider_frames(provider):
    initial = '{"answer":"First'
    tail = ' part","citations":["fixture"]}'
    if provider == "openai":
        frames = [{"choices": [{"delta": {"content": value}}]} for value in (initial, tail)]
        frames += [{"choices": [], "usage": {"prompt_tokens": 9, "completion_tokens": 4}}, "[DONE]"]
    elif provider == "anthropic":
        frames = [{"type": "message_start", "message": {"usage": {"input_tokens": 9}}}]
        frames += [{"type": "content_block_delta", "delta": {"text": value}} for value in (initial, tail)]
        frames += [{"type": "message_delta", "usage": {"output_tokens": 4}}, {"type": "message_stop"}]
    elif provider == "gemini":
        frames = [{"candidates": [{"content": {"parts": [{"text": initial}]}}]},
                  {"candidates": [{"content": {"parts": [{"text": tail}]}, "finishReason": "STOP"}],
                   "usageMetadata": {"promptTokenCount": 9, "candidatesTokenCount": 4}}]
    else:
        frames = [{"message": {"content": initial}}, {"message": {"content": tail}},
                  {"done": True, "prompt_eval_count": 9, "eval_count": 4}]
    lines = [(frame if isinstance(frame, str) else json.dumps(frame)) for frame in frames]
    body = "".join((f"{line}\n" if provider == "ollama" else f"data: {line}\n\n") for line in lines)

    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self):
            encoded = body.encode()
            for offset in range(0, len(encoded), 7):
                yield encoded[offset:offset + 7]

    def mock(request):
        if provider == "gemini":
            assert request.url.params["alt"] == "sse"
        else:
            assert json.loads(request.content)["stream"] is True
        return httpx.Response(200, stream=Chunks())

    partial = []

    async def track(text):
        partial.append(text)

    result = asyncio.run(native_stream(Connection(provider, "https://api.example", {}), "model",
        timeout=3, prompt=("System", "Source"), limit=60, on_partial=track, transport=httpx.MockTransport(mock)))
    assert partial == ["First", "First part"]
    assert result == ({"answer": "First part", "citations": ["fixture"]}, 9, 4)


def test_interrupted_provider_stream_does_not_finalize():
    async def unused(_partial):
        return None

    transport = httpx.MockTransport(lambda request: httpx.Response(200, content='data: {"choices": []}\n\n'))
    with pytest.raises(ProviderError, match="stream_incomplete"):
        asyncio.run(native_stream(Connection("openai", "https://api.example", {}), "model",
            timeout=3, prompt=("System", "Source"), limit=60, on_partial=unused, transport=transport))


def test_copilot_stream_persists_only_the_cited_final_answer(client, monkeypatch):
    _, auth = register(client, "stream")
    _, foreign = register(client, "stream-foreign")
    monkeypatch.setenv("VYRNEXIS_AI_ENABLE_LOCAL", "1")
    monkeypatch.setenv("VYRNEXIS_AI_OLLAMA_URL", "http://127.0.0.1:11434")
    assert client.put("/api/v1/ai/settings", headers=auth, json={
        "mode": "assisted", "provider": "ollama", "model": "fixture", "allow_model_context": True,
    }).status_code == 200
    assert upload(client, auth, "Synthetic policy", b"Cobalt controls require a second review.").status_code == 201
    path = conversation(client, auth)
    payload = {"request_key": "stream-unique-test", "text": "cobalt", "mode": "model_assisted", "acknowledge_model_context": True}

    async def mock(connection, model, **options):
        await options["on_partial"]("Recorded policy")
        citation = json.loads(options["prompt"][1])["sources"][0]["key"]
        return {"answer": "Recorded policy requires review.", "citations": [citation]}, 10, 6

    monkeypatch.setattr("app.copilot.native_stream", mock)
    assert client.post(path + "/stream", headers=foreign, json=payload).status_code == 404
    result = client.post(path + "/stream", headers=auth, json=payload)
    assert result.status_code == 200 and result.headers["content-type"].startswith("text/event-stream")
    assert "event: partial" in result.text and "event: done" in result.text
    saved = client.get(path, headers=auth).json()["turns"]
    assert len(saved) == 1 and saved[0]["answer"] == "Recorded policy requires review."
    assert saved[0]["sources"][0]["title"] == "Synthetic policy"
    assert client.get("/api/v1/ai/settings", headers=auth).json()["recent_usage"][0]["output_tokens"] == 6
