import logging

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import verify_app_token
from app.db.crud import get_or_create_user
from app.db.database import get_db
from app.db.models import User
from app.security.audit import AUTH_FAILURE, AUTH_SUCCESS, NEW_USER, record

logger = logging.getLogger(__name__)

_bearer = HTTPBearer()


async def get_current_user(
    http_request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    try:
        payload = await verify_app_token(credentials.credentials)
    except HTTPException:
        await record(
            event_type=AUTH_FAILURE,
            endpoint=str(http_request.url.path),
            field_name="Authorization",
            extra=f"ip={http_request.client.host if http_request.client else 'unknown'}",
            db=db,
        )
        raise

    google_id: str | None = payload.get("sub")
    email: str = payload.get("email", "")

    if not google_id:
        await record(
            event_type=AUTH_FAILURE,
            endpoint=str(http_request.url.path),
            field_name="sub",
            extra="missing_sub_claim",
            db=db,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject claim",
        )

    user, created = await get_or_create_user(db, clerk_id=google_id, email=email)
    http_request.state.user = user

    if created:
        await record(
            event_type=NEW_USER,
            endpoint=str(http_request.url.path),
            field_name="",
            user_id=user.id,
            extra=f"email={email}",
            db=db,
        )
    else:
        logger.debug("auth_success | user=%s endpoint=%s", user.id, http_request.url.path)

    return user
