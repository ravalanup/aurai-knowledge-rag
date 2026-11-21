import httpx
import pytest

from aurai_knowledge.embeddings import (
    EmbeddingError,
    EmbeddingRejected,
    GatewayEmbedder,
    HashEmbedder,
    build_embedder,
)
from aurai_knowledge.settings import Settings


def gateway(handler, **kw):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return GatewayEmbedder("http://gw.test:4000/", "sk-test", client=client, **kw)


def ok(request):
    inputs = __import__("json").loads(request.content)["input"]
    # return out of order to prove the embedder sorts by index
    data = [{"index": i, "embedding": [float(i), 1.0]} for i in range(len(inputs))][::-1]
    return httpx.Response(200, json={"data": data})


def test_sends_alias_key_and_batches():
    seen = []

    def handler(request):
        seen.append(request)
        return ok(request)

    vectors = gateway(handler, batch_size=2).embed(["a", "b", "c"])
    assert [v[0] for v in vectors] == [0.0, 1.0, 0.0]  # per-batch order restored
    assert len(seen) == 2
    assert seen[0].url.path == "/v1/embeddings" and seen[0].headers["authorization"] == "Bearer sk-test"
    assert __import__("json").loads(seen[0].content)["model"] == "aurai-embed"


def test_dimensions_are_sent_only_when_configured():
    bodies = []

    def handler(request):
        bodies.append(__import__("json").loads(request.content))
        return ok(request)

    gateway(handler).embed(["a"])
    gateway(handler, dimensions=768).embed(["a"])
    assert "dimensions" not in bodies[0] and bodies[1]["dimensions"] == 768


def test_retries_transient_errors(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _s: None)
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503) if len(calls) < 3 else ok(request)

    assert len(gateway(handler, retries=2).embed(["a"])) == 1 and len(calls) == 3


def test_persistent_failure_raises_without_leaking_detail(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _s: None)
    with pytest.raises(EmbeddingError) as err:
        gateway(lambda r: httpx.Response(500, text="secret upstream detail"), retries=1).embed(["a"])
    assert "secret" not in str(err.value)


def test_wrong_count_is_an_error():
    with pytest.raises(EmbeddingError):
        gateway(lambda r: httpx.Response(200, json={"data": []}), retries=0).embed(["a"])


def test_hash_embedder_is_deterministic_and_normalised():
    e = HashEmbedder(64)
    a, b = e.embed(["refund tickets"])[0], e.embed(["refund tickets"])[0]
    assert a == b and abs(sum(x * x for x in a) - 1) < 1e-9
    similar = sum(x * y for x, y in zip(a, e.embed(["ticket refund policy"])[0], strict=True))
    unrelated = sum(x * y for x, y in zip(a, e.embed(["lantern walk fireworks"])[0], strict=True))
    assert similar > unrelated


def test_build_embedder_validates_settings():
    assert isinstance(build_embedder(Settings(embedder="hash")), HashEmbedder)
    with pytest.raises(EmbeddingError, match="GATEWAY_KEY"):
        build_embedder(Settings(embedder="gateway", gateway_key=""))
    with pytest.raises(EmbeddingError, match="unknown embedder"):
        build_embedder(Settings(embedder="magic"))
    assert isinstance(build_embedder(Settings(embedder="gateway", gateway_key="k")), GatewayEmbedder)


def test_gateway_policy_rejection_is_not_retried_and_never_echoes_input():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(400, json={"error": {"code": "pii_blocked", "message": "SSN 123-45-6789 found"}})

    with pytest.raises(EmbeddingRejected) as err:
        gateway(handler, retries=2).embed(["my ssn is 123-45-6789"])
    assert len(calls) == 1 and "pii_blocked" in str(err.value) and "123-45" not in str(err.value)
