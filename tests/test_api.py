"""The HTTP surface: the contract, authentication, and the entitlement matrix."""

import json
from pathlib import Path

import jsonschema
import pytest
import yaml

from .conftest import ROOT, auth

CONTRACT = yaml.safe_load((ROOT / "contracts" / "knowledge-service.openapi.yaml").read_text())
FINANCE_DOC = "finance-reporting/q3-revenue-summary.md"


def search(client, token, query="refund policy for tickets", **body):
    return client.post("/v1/search", json={"query": query, **body}, headers=auth(token))


def schema(name):
    return {"$ref": f"#/components/schemas/{name}", "components": CONTRACT["components"]}


def doc_ids(response):
    return {p["source"]["uri"].removeprefix("kb://") for p in response.json()["results"]}


def test_health_endpoints(client):
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200


def test_response_conforms_to_the_contract(client, mint):
    response = search(client, mint(), top_k=3)
    assert response.status_code == 200
    jsonschema.validate(response.json(), schema("SearchResponse"))
    assert 0 < len(response.json()["results"]) <= 3


def test_every_passage_carries_a_citation(client, mint):
    for passage in search(client, mint(["knowledge-ops", "workspace-members"]), "skyline wheel").json()["results"]:
        source = passage["source"]
        assert source["title"] and source["uri"].startswith("kb://") and source["collection"]
        assert source["classification"] in {"public", "internal", "confidential", "restricted"}
        assert len(source["freshness"]) == 10


def test_results_are_ranked_best_first(client, mint):
    scores = [p["score"] for p in search(client, mint(), "refund tickets", top_k=8).json()["results"]]
    assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------- authentication
def test_missing_token_is_401(client):
    response = client.post("/v1/search", json={"query": "x"})
    assert response.status_code == 401 and response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("header", ["Bearer", "Basic abc", "Bearer not-a-jwt", "bearer "])
def test_bad_authorization_headers_are_401(client, header):
    assert client.post("/v1/search", json={"query": "x"}, headers={"Authorization": header}).status_code == 401


def test_expired_and_foreign_tokens_are_401(client, mint, other_key):
    assert search(client, mint(exp=1)).status_code == 401
    assert search(client, mint(key=other_key)).status_code == 401


def test_authentication_is_checked_before_the_body(client):
    assert client.post("/v1/search", json={"nonsense": True}).status_code == 401


def test_identity_comes_from_the_token_not_the_body(client, mint):
    response = search(client, mint(["workspace-members"]), groups=["knowledge-finance"], user="finance-director")
    assert response.status_code == 422  # unknown fields are refused, so they cannot be smuggled in


# ---------------------------------------------------------------- validation
@pytest.mark.parametrize(
    "body",
    [
        {},
        {"query": ""},
        {"query": "   "},
        {"query": "x" * 2001},
        {"query": "ok", "top_k": 0},
        {"query": "ok", "top_k": 21},
        {"query": "ok", "collections": "guest-services"},
        {"query": "ok", "extra": 1},
    ],
)
def test_malformed_requests_are_422(client, mint, body):
    assert client.post("/v1/search", json=body, headers=auth(mint())).status_code == 422


def test_boundary_values_are_accepted(client, mint):
    assert search(client, mint(), "x" * 2000, top_k=20).status_code == 200
    assert search(client, mint(), "refund", top_k=1).status_code == 200


# ---------------------------------------------------------------- entitlement matrix
GRANTS = {
    # persona groups -> (collection, highest classification they may see)
    ("workspace-members",): {"guest-services": "internal", "hr-policies": "internal"},
    ("workspace-builders",): {"guest-services": "internal", "hr-policies": "internal", "ops-reports": "internal"},
    ("workspace-members", "knowledge-ops"): {
        "guest-services": "internal",
        "hr-policies": "internal",
        "ops-reports": "confidential",
    },
    ("workspace-members", "knowledge-hr"): {"guest-services": "internal", "hr-policies": "restricted"},
    ("workspace-members", "knowledge-finance"): {
        "guest-services": "internal",
        "hr-policies": "internal",
        "finance-reporting": "restricted",
    },
}
RANK = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
BROAD_QUERIES = [
    "salary range band",
    "revenue attendance quarter",
    "capital budget Project Lantern",
    "Skyline Wheel stall root cause",
    "medical leave certification",
    "refund tickets",
    "downtime maintenance staffing energy",
    "vendor payment terms discount",
]


@pytest.mark.parametrize("groups", list(GRANTS))
def test_nobody_ever_receives_a_passage_above_their_grant(client, mint, groups):
    grants = GRANTS[groups]
    token = mint(groups)
    for query in BROAD_QUERIES:
        for passage in search(client, token, query, top_k=20).json()["results"]:
            source = passage["source"]
            assert source["collection"] in grants, f"{groups} saw {source['collection']}"
            assert RANK[source["classification"]] <= RANK[grants[source["collection"]]], f"{groups} saw {source}"


def test_restricted_content_reaches_only_its_owners(client, mint):
    owners = search(client, mint(["knowledge-hr"]), "salary range Band 5", top_k=20)
    assert "hr-policies/compensation-bands-2026.md" in doc_ids(owners)
    for groups in (["workspace-members"], ["workspace-builders"], ["knowledge-ops"], ["knowledge-finance"]):
        others = search(client, mint(groups), "salary range Band 5", top_k=20)
        assert "hr-policies/compensation-bands-2026.md" not in doc_ids(others), groups


def test_requesting_a_forbidden_collection_is_403(client, mint):
    assert search(client, mint(), collections=["finance-reporting"]).status_code == 403


def test_nonexistent_and_forbidden_collections_look_identical(client, mint):
    forbidden = search(client, mint(), collections=["finance-reporting"])
    missing = search(client, mint(), collections=["no-such-collection"])
    assert forbidden.status_code == missing.status_code == 403
    assert forbidden.json() == missing.json()


def test_collection_filter_narrows_but_never_widens(client, mint):
    token = mint(["workspace-members"])
    response = search(client, token, "refund", collections=["guest-services", "finance-reporting"], top_k=20)
    assert response.status_code == 200
    assert {p["source"]["collection"] for p in response.json()["results"]} == {"guest-services"}


def test_caller_with_no_grants_gets_403_not_an_empty_list(client, mint):
    assert search(client, mint(["workspace-admins"])).status_code == 403
    assert search(client, mint([])).status_code == 403
    assert search(client, mint(None)).status_code == 403


def test_forbidden_documents_are_omitted_not_redacted(client, mint):
    body = json.dumps(search(client, mint(["workspace-members"]), "Project Lantern capital plan", top_k=20).json())
    assert "Lantern" not in body and "restricted" not in body and "finance" not in body.lower()


# ---------------------------------------------------------------- failure behaviour
def test_embedding_outage_is_503(client, mint, embedder, monkeypatch):
    from aurai_knowledge.embeddings import EmbeddingError

    def boom(_texts):
        raise EmbeddingError("gateway down")

    monkeypatch.setattr(embedder, "embed", boom)
    response = search(client, mint())
    assert response.status_code == 503 and "gateway" not in response.text.lower()


def test_query_refused_by_the_data_policy_is_422(client, mint, embedder, monkeypatch):
    from aurai_knowledge.embeddings import EmbeddingRejected

    def refuse(_texts):
        raise EmbeddingRejected("input rejected by the gateway (pii_blocked)")

    monkeypatch.setattr(embedder, "embed", refuse)
    response = search(client, mint(), "my card number is 4111 1111 1111 1111")
    assert response.status_code == 422 and "4111" not in response.text


def test_index_outage_is_503_and_reported_by_readyz(client, mint, store, monkeypatch):
    def broken(*_a, **_k):
        raise RuntimeError("qdrant down")

    monkeypatch.setattr(store._client, "query_points", broken)
    monkeypatch.setattr(store._client, "collection_exists", broken)
    response = search(client, mint())
    assert response.status_code == 503 and "qdrant" not in response.text.lower()
    assert client.get("/readyz").status_code == 503


# ---------------------------------------------------------------- tracing and logging
def test_retrieval_span_follows_the_aurai_conventions(client, mint, span_exporter):
    search(client, mint(["workspace-members", "knowledge-ops"]), "downtime", top_k=4, collections=None)
    span = next(s for s in span_exporter.get_finished_spans() if s.name == "aurai.retrieval")
    attrs = span.attributes
    assert attrs["aurai.use_case.id"] == "knowledge-search" and attrs["aurai.risk_tier"] == "T2"
    assert attrs["aurai.retrieval.collection"] == "guest-services,hr-policies,ops-reports"
    assert 1 <= attrs["aurai.retrieval.source_count"] <= 4


def test_span_records_workspace_trace_id_and_never_the_query(client, mint, span_exporter):
    client.post(
        "/v1/search",
        json={"query": "a very private question about Project Lantern"},
        headers={**auth(mint(["knowledge-finance"])), "X-Aurai-Trace-Id": "trace-abc"},
    )
    span = next(s for s in span_exporter.get_finished_spans() if s.name == "aurai.retrieval")
    assert span.attributes["aurai.workspace.trace_id"] == "trace-abc"
    assert "Lantern" not in json.dumps(dict(span.attributes))


def test_query_text_is_not_logged(client, mint, caplog):
    caplog.set_level("INFO", logger="aurai.knowledge")
    search(client, mint(), "a very private question")
    assert "private" not in caplog.text and "outcome=ok" in caplog.text


def test_openapi_paths_match_the_contract(client):
    spec = client.get("/openapi.json").json()
    assert set(CONTRACT["paths"]) <= set(spec["paths"]) | {"/healthz"}
    assert Path(ROOT / "contracts" / "knowledge-service.openapi.yaml").exists()
