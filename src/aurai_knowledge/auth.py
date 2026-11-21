"""Verification of the caller's Keycloak access token. Identity comes only from a verified token."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import jwt

from .models import Identity


class AuthError(Exception):
    """The token is missing, malformed, expired or not meant for this service."""


class TokenVerifier:
    def __init__(
        self,
        issuer: str,
        audience: str,
        jwks_url: str | None = None,
        key_resolver: Callable[[str], Any] | None = None,
        algorithms: tuple[str, ...] = ("RS256",),
        leeway_seconds: int = 10,
    ) -> None:
        if not key_resolver and not jwks_url:
            raise ValueError("provide a jwks_url or a key_resolver")
        self._issuer = issuer
        self._audience = audience
        self._algorithms = list(algorithms)
        self._leeway = leeway_seconds
        if key_resolver:
            self._resolve = key_resolver
        else:
            client = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=600)  # type: ignore[arg-type]
            self._resolve = lambda token: client.get_signing_key_from_jwt(token).key

    def verify(self, token: str) -> Identity:
        try:
            key = self._resolve(token)
            claims = jwt.decode(
                token,
                key=key,
                algorithms=self._algorithms,
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthError(type(exc).__name__) from exc
        except Exception as exc:  # key lookup failures (JWKS unreachable) must not become a pass
            raise AuthError("key-resolution-failed") from exc
        return Identity(
            subject=str(claims["sub"]),
            groups=frozenset(_normalise(g) for g in claims.get("groups") or []),
            roles=frozenset(str(r) for r in claims.get("roles") or []),
        )


def _normalise(group: object) -> str:
    """Keycloak can emit group paths ('/knowledge-ops'); the policy uses short names."""
    return str(group).strip().lstrip("/")
