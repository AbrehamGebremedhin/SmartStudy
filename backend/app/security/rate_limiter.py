from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def _get_user_key(request: Request) -> str:
    """Rate-limit by authenticated user ID when available, else by IP."""
    user = getattr(request.state, "user", None)
    if user is not None and hasattr(user, "id"):
        return str(user.id)
    return get_remote_address(request)


limiter = Limiter(key_func=_get_user_key, default_limits=["200/minute"])
