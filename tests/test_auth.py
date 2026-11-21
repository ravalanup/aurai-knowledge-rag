import time

import pytest

from aurai_knowledge.auth import AuthError

from .conftest import AUDIENCE, ISSUER  # noqa: F401


def test_valid_token_yields_identity(verifier, mint):
    identity = verifier.verify(mint(groups=["workspace-members", "/knowledge-ops"]))
    assert identity.subject == "user-1234"
    assert identity.groups == {"workspace-members", "knowledge-ops"}  # group paths are normalised
    assert "member" in identity.roles


@pytest.mark.parametrize(
    "overrides",
    [
        {"exp": int(time.time()) - 3600},
        {"aud": "someone-else"},
        {"iss": "http://evil.test/realms/aurai"},
        {"sub": None},
        {"exp": None},
    ],
)
def test_bad_claims_are_rejected(verifier, mint, overrides):
    with pytest.raises(AuthError):
        verifier.verify(mint(**overrides))


def test_token_signed_by_another_key_is_rejected(verifier, mint, other_key):
    with pytest.raises(AuthError):
        verifier.verify(mint(key=other_key))


def test_garbage_is_rejected(verifier):
    with pytest.raises(AuthError):
        verifier.verify("not-a-jwt")


def test_alg_none_is_rejected(verifier):
    import jwt

    token = jwt.encode(
        {"iss": ISSUER, "aud": AUDIENCE, "sub": "x", "exp": int(time.time()) + 60}, key=None, algorithm="none"
    )
    with pytest.raises(AuthError):
        verifier.verify(token)


def test_key_lookup_failure_is_a_denial_not_an_error(mint):
    from aurai_knowledge.auth import TokenVerifier

    def broken(_token):
        raise ConnectionError("jwks unreachable")

    with pytest.raises(AuthError):
        TokenVerifier(ISSUER, AUDIENCE, key_resolver=broken).verify(mint())


def test_missing_groups_claim_means_no_groups(verifier, mint):
    assert verifier.verify(mint(groups=None)).groups == frozenset()
