import base64
import json

import httpx

from app.models import KnowledgeEmbedding, KnowledgeEmbeddingJob
from app.semantic import EmbeddingProvider, process_embeddings
from test_ai_workspace import same_tenant_viewer
from test_api import register


def test_ollama_embedding_transport_uses_real_vector_shape():
    provider = EmbeddingProvider("http://localhost:11434", "fixture", "2")

    def reply(request):
        assert request.url.path == "/api/embed"
        assert json.loads(request.content)["input"] == ["Synthetic passage"]
        assert json.loads(request.content)["truncate"] is False
        return httpx.Response(200, json={"embeddings": [[3, 4]]})

    assert provider.embed(["Synthetic passage"], httpx.MockTransport(reply)) == [[.6, .8]]


def test_hybrid_retrieval_requires_authorized_vectors_and_cleans_up(client, monkeypatch):
    monkeypatch.setenv("VYRNEXIS_EMBEDDINGS_ENABLED", "1")
    monkeypatch.setenv("VYRNEXIS_EMBEDDING_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("VYRNEXIS_EMBEDDING_MODEL", "fixture")
    monkeypatch.setenv("VYRNEXIS_DETECTION_MODE", "worker")
    owner, auth = register(client, "semantic")
    _, foreign = register(client, "semantic-foreign")
    viewer = same_tenant_viewer(client, owner)
    seen = []

    def mock_embed(self, inputs, transport=None):
        seen.extend(inputs)
        return [[1.0, 0.0] for _ in inputs]

    monkeypatch.setattr(EmbeddingProvider, "embed", mock_embed)
    path = "/api/v1/knowledge/documents"
    upload = client.post(path, headers=auth, json={"title": "Private document", "filename": "policy.txt",
        "content_base64": base64.b64encode(b"Raspberry material").decode()})
    assert upload.status_code == 201, upload.text
    doc = upload.json()["id"]
    index = f"{path}/{doc}/embedding"
    assert client.post(index, headers=auth, json={"acknowledge_local_processing": False}).status_code == 422
    request = {"acknowledge_local_processing": True}
    queued = client.post(index, headers=auth, json=request)
    assert queued.status_code == 202 and queued.json()["status"] == "queued", queued.text
    assert not seen
    test_factory = client.app.state.test_session_factory
    assert process_embeddings(doc, test_factory)
    assert not process_embeddings(doc, test_factory)
    assert client.get(index, headers=auth).json()["status"] == "completed"
    assert client.get(index, headers=viewer).status_code == 404
    search = "/api/v1/knowledge/search/hybrid"
    terms = request | {"query": "unmatched lexical query"}
    for unauthorized in (foreign, viewer):
        denied = client.post(search, headers=unauthorized, json=terms).json()
        assert denied["sources"] == [] and denied["method"] == "keyword"
    assert seen == ["Raspberry material"]
    authorized = client.post(search, headers=auth, json=terms)
    assert authorized.status_code == 200, authorized.text
    assert authorized.json()["method"] == "hybrid" and authorized.json()["sources"][0]["document_id"] == doc
    assert client.delete(f"{path}/{doc}", headers=auth).status_code == 204
    with test_factory() as db:
        assert db.query(KnowledgeEmbeddingJob).count() == 0
        assert db.query(KnowledgeEmbedding).count() == 0
