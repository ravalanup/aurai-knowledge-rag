from aurai_knowledge.settings import Settings


def test_defaults_point_at_in_cluster_services():
    s = Settings()
    assert s.qdrant_url.endswith("aurai-system.svc.cluster.local:6333")
    assert (
        s.jwks_url == "http://keycloak.aurai-system.svc.cluster.local:8080/realms/aurai/protocol/openid-connect/certs"
    )


def test_environment_overrides(monkeypatch):
    monkeypatch.setenv("AURAI_EMBED_DIMENSIONS", "768")
    monkeypatch.setenv("AURAI_MIN_SCORE", "0.3")
    monkeypatch.setenv("AURAI_OIDC_JWKS_URL", "http://jwks.test/certs")
    monkeypatch.setenv("AURAI_GATEWAY_KEY", "sk-x")
    s = Settings.from_env()
    assert s.embed_dimensions == 768 and s.min_score == 0.3 and s.jwks_url == "http://jwks.test/certs"
    assert s.gateway_key == "sk-x"


def test_blank_numeric_variables_use_defaults(monkeypatch):
    monkeypatch.setenv("AURAI_EMBED_DIMENSIONS", "")
    assert Settings.from_env().embed_dimensions is None
