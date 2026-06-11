from fastapi import APIRouter
from pydantic import BaseModel

from app.auth.google import verify_token
from app.auth.tokens import create_app_token

router = APIRouter()


class GoogleLoginRequest(BaseModel):
    credential: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/auth/login", response_model=TokenResponse)
async def google_login(body: GoogleLoginRequest) -> TokenResponse:
    google_payload = await verify_token(body.credential)
    app_token = create_app_token(google_payload)
    return TokenResponse(access_token=app_token)
