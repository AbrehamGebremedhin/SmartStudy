from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.google import verify_token
from app.db.crud import get_or_create_user
from app.db.database import get_db
from app.db.models import User

_bearer = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    payload = await verify_token(credentials.credentials)

    google_id: str | None = payload.get("sub")
    email: str = payload.get("email", "")

    if not google_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject claim",
        )

    return await get_or_create_user(db, clerk_id=google_id, email=email)
