import time
from typing import Any

import httpx
from fastapi import HTTPException, status
from jose import JWTError, jwt

from app.config import settings

_GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
_GOOGLE_ISSUERS = {"https://accounts.google.com", "accounts.google.com"}

_jwks_cache: dict[str, Any] = {}
_jwks_fetched_at: float = 0.0
_JWKS_TTL = 3600  # refresh every hour


async def _get_jwks() -> dict[str, Any]:
    global _jwks_cache, _jwks_fetched_at

    now = time.monotonic()
    if _jwks_cache and (now - _jwks_fetched_at) < _JWKS_TTL:
        return _jwks_cache

    async with httpx.AsyncClient() as client:
        response = await client.get(_GOOGLE_JWKS_URL)
        response.raise_for_status()

    _jwks_cache = response.json()
    _jwks_fetched_at = now
    return _jwks_cache


async def verify_token(token: str) -> dict[str, Any]:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        jwks = await _get_jwks()
        header = jwt.get_unverified_header(token)
        key = next(
            (k for k in jwks["keys"] if k["kid"] == header.get("kid")),
            None,
        )
        if key is None:
            raise credentials_error

        payload = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=settings.google_client_id,
        )

        if payload.get("iss") not in _GOOGLE_ISSUERS:
            raise credentials_error

        return payload

    except JWTError:
        raise credentials_error
    except httpx.HTTPError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable",
        )
