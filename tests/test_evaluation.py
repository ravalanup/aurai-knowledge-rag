import pytest

from aurai_knowledge.evaluation import evaluate, load_golden

from .conftest import ROOT

GOLDEN = ROOT / "eval" / "golden-set.yaml"


def real_search(service):
    from aurai_knowledge.models import Identity
    from aurai_knowledge.service import Forbidden

    def search(groups, query, top_k, collections):
        try:
            out = service.search(Identity("eval", groups, frozenset()), query, collections, top_k)
        except Forbidden:
            return []
        return [(h.doc_id, h.collection, h.classification.label) for h in out.hits]

    return search


@pytest.fixture
def service(policy, store, embedder):
    from aurai_knowledge.service import SearchService

    return SearchService(policy, store, embedder)


def test_shipped_golden_set_passes_its_thresholds(policy, service):
    golden = load_golden(str(GOLDEN))
    report = evaluate(golden, policy, real_search(service), top_k=5)
    assert report.failures() == []
    assert report.leaks == 0 and report.hit_rate >= 0.85


def test_harness_detects_a_leaky_retriever(policy):
    """A retriever that ignores entitlements must fail the evaluation; otherwise the gate proves nothing."""
    golden = load_golden(str(GOLDEN))

    def leaky(groups, query, top_k, collections):
        return [("hr-policies/compensation-bands-2026.md", "hr-policies", "restricted")]

    report = evaluate(golden, policy, leaky, top_k=5)
    assert report.leaks > 0
    assert any("leaked" in f for f in report.failures())


def test_harness_detects_poor_relevance(policy):
    golden = load_golden(str(GOLDEN))
    report = evaluate(golden, policy, lambda *_: [("guest-services/seasonal-hours.txt", "guest-services", "public")], 5)
    assert report.hit_rate < 0.85 and any("hit_rate" in f for f in report.failures())


def test_expect_empty_fails_when_something_comes_back(policy):
    golden = load_golden(str(GOLDEN))
    report = evaluate(golden, policy, lambda *_: [("guest-services/refund-policy.md", "guest-services", "public")], 5)
    assert any("expected no results" in f for f in report.failures())


def test_mrr_reflects_rank(policy):
    golden = {
        "version": 1,
        "thresholds": {},
        "personas": {"p": {"groups": ["workspace-members"]}},
        "cases": [{"id": "c", "persona": "p", "query": "q", "expected": ["guest-services/b.md"]}],
    }
    docs = [("guest-services/a.md", "guest-services", "public"), ("guest-services/b.md", "guest-services", "public")]
    report = evaluate(golden, policy, lambda *_: docs, 5)
    assert report.mrr == 0.5 and report.hit_rate == 1.0


@pytest.mark.parametrize(
    "mutation",
    [
        {"version": 2},
        {"cases": []},
        {"cases": [{"id": "x", "persona": "ghost", "query": "q", "expected": ["a"]}]},
        {"cases": [{"id": "x", "persona": "p", "query": "q"}]},
    ],
)
def test_invalid_golden_sets_are_rejected(tmp_path, mutation):
    import yaml

    base = {
        "version": 1,
        "personas": {"p": {"groups": ["g"]}},
        "cases": [{"id": "x", "persona": "p", "query": "q", "expected": ["a"]}],
    }
    path = tmp_path / "g.yaml"
    path.write_text(yaml.safe_dump({**base, **mutation}))
    with pytest.raises(ValueError):
        load_golden(str(path))
