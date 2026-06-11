from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, status
from jose import JWTError, jwt

from app.config import settings

_ALGORITHM = "HS256"


def create_app_token(google_payload: dict[str, Any]) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=settings.app_token_expire_days)
    claims = {
        "sub": google_payload["sub"],
        "email": google_payload.get("email", ""),
        "name": google_payload.get("name", ""),
        "picture": google_payload.get("picture", ""),
        "iat": now,
        "exp": expire,
    }
    return jwt.encode(claims, settings.secret_key, algorithm=_ALGORITHM)


async def verify_app_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[_ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
