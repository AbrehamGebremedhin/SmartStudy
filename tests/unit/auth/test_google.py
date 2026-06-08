"""
Unit tests for app/auth/google.py.

Google JWKS fetching is mocked via respx; JWT signing uses python-jose directly
so we can create valid test tokens without hitting Google's servers.
"""
import time
from unittest.mock import patch

import pytest
import respx
from fastapi import HTTPException
from httpx import Response
from jose import jwt

import app.auth.google as google_module


# ---------------------------------------------------------------------------
# Helpers — we cannot sign RS256 tokens in tests easily without a real key,
# so we test the HTTP-layer behavior (JWKS caching) and the error paths
# (missing key, JWKS service down, JWTError) by patching jwt.decode.
# ---------------------------------------------------------------------------


FAKE_JWKS = {
    "keys": [
        {
            "kid": "test-key-id",
            "kty": "RSA",
            "alg": "RS256",
            "use": "sig",
            "n": "sampleN",
            "e": "AQAB",
        }
    ]
}


@pytest.fixture(autouse=True)
def reset_jwks_cache():
    """Clear the module-level JWKS cache before each test."""
    google_module._jwks_cache = {}
    google_module._jwks_fetched_at = 0.0
    yield
    google_module._jwks_cache = {}
    google_module._jwks_fetched_at = 0.0


# ---------------------------------------------------------------------------
# _get_jwks — caching behaviour
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetJwks:
    @respx.mock
    async def test_fetches_jwks_on_first_call(self):
        respx.get(google_module._GOOGLE_JWKS_URL).mock(
            return_value=Response(200, json=FAKE_JWKS)
        )
        result = await google_module._get_jwks()
        assert result == FAKE_JWKS

    @respx.mock
    async def test_uses_cache_on_second_call_within_ttl(self):
        route = respx.get(google_module._GOOGLE_JWKS_URL).mock(
            return_value=Response(200, json=FAKE_JWKS)
        )
        await google_module._get_jwks()
        await google_module._get_jwks()
        assert route.call_count == 1  # only fetched once

    @respx.mock
    async def test_refetches_after_ttl_expires(self):
        route = respx.get(google_module._GOOGLE_JWKS_URL).mock(
            return_value=Response(200, json=FAKE_JWKS)
        )
        await google_module._get_jwks()
        # Simulate cache expiry by back-dating the fetch timestamp
        google_module._jwks_fetched_at -= google_module._JWKS_TTL + 1
        await google_module._get_jwks()
        assert route.call_count == 2

    @respx.mock
    async def test_http_error_propagates_from_get_jwks(self):
        """_get_jwks raises HTTPStatusError on non-2xx; verify_token converts it to 503."""
        from httpx import HTTPStatusError
        respx.get(google_module._GOOGLE_JWKS_URL).mock(return_value=Response(500))
        # _get_jwks itself does NOT catch HTTPStatusError — it propagates.
        # verify_token is responsible for converting it to a 503 HTTPException.
        with pytest.raises(HTTPStatusError):
            await google_module._get_jwks()


# ---------------------------------------------------------------------------
# verify_token — error paths
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestVerifyToken:
    @respx.mock
    async def test_missing_key_id_raises_401(self):
        """Token whose kid does not match any key in JWKS → 401."""
        respx.get(google_module._GOOGLE_JWKS_URL).mock(
            return_value=Response(200, json=FAKE_JWKS)
        )
        # Patch jwt.get_unverified_header to return a kid that's NOT in FAKE_JWKS
        with patch("app.auth.google.jwt.get_unverified_header", return_value={"kid": "unknown-kid"}):
            with pytest.raises(HTTPException) as exc_info:
                await google_module.verify_token("dummy.token.value")
            assert exc_info.value.status_code == 401

    @respx.mock
    async def test_jwt_error_raises_401(self):
        """JWTError from decode → 401."""
        from jose import JWTError

        respx.get(google_module._GOOGLE_JWKS_URL).mock(
            return_value=Response(200, json=FAKE_JWKS)
        )
        with patch("app.auth.google.jwt.get_unverified_header", return_value={"kid": "test-key-id"}):
            with patch("app.auth.google.jwt.decode", side_effect=JWTError("expired")):
                with pytest.raises(HTTPException) as exc_info:
                    await google_module.verify_token("bad.token")
                assert exc_info.value.status_code == 401
                assert "Invalid" in exc_info.value.detail

    @respx.mock
    async def test_wrong_issuer_raises_401(self):
        """Token with an issuer not in _GOOGLE_ISSUERS → 401."""
        respx.get(google_module._GOOGLE_JWKS_URL).mock(
            return_value=Response(200, json=FAKE_JWKS)
        )
        fake_payload = {
            "sub": "12345",
            "email": "user@example.com",
            "iss": "https://evil.com",  # not in _GOOGLE_ISSUERS
        }
        with patch("app.auth.google.jwt.get_unverified_header", return_value={"kid": "test-key-id"}):
            with patch("app.auth.google.jwt.decode", return_value=fake_payload):
                with pytest.raises(HTTPException) as exc_info:
                    await google_module.verify_token("fake.token")
                assert exc_info.value.status_code == 401

    @respx.mock
    async def test_valid_token_returns_payload(self):
        """Happy path: valid issuer → payload returned."""
        respx.get(google_module._GOOGLE_JWKS_URL).mock(
            return_value=Response(200, json=FAKE_JWKS)
        )
        fake_payload = {
            "sub": "google-uid-123",
            "email": "user@example.com",
            "iss": "https://accounts.google.com",
        }
        with patch("app.auth.google.jwt.get_unverified_header", return_value={"kid": "test-key-id"}):
            with patch("app.auth.google.jwt.decode", return_value=fake_payload):
                result = await google_module.verify_token("valid.token")
        assert result["sub"] == "google-uid-123"
        assert result["email"] == "user@example.com"

    @respx.mock
    async def test_jwks_unavailable_raises_503(self):
        """JWKS endpoint HTTP error → 503."""
        respx.get(google_module._GOOGLE_JWKS_URL).mock(return_value=Response(503))
        with pytest.raises(HTTPException) as exc_info:
            await google_module.verify_token("any.token")
        assert exc_info.value.status_code == 503
