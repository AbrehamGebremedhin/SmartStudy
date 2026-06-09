"""
Structured security audit logging.

All security-relevant events are written to:
1. The `security_events` database table (durable, queryable).
2. Python's logger as a fallback when the DB is unavailable (so events are
   never silently lost — they'll appear in stdout/log aggregation at minimum).
"""

import logging
from collections.abc import AsyncGenerator

logger = logging.getLogger("smartstudy.security")

# Event type constants — use these everywhere to keep event_type values consistent
AUTH_SUCCESS = "auth_success"
AUTH_FAILURE = "auth_failure"
NEW_USER = "new_user"
INJECTION_ATTEMPT = "injection_attempt"
RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
GENERATION_REQUEST = "generation_request"


async def record(
    event_type: str,
    endpoint: str,
    field_name: str = "",
    user_id=None,
    extra: str = "",
    db=None,
) -> None:
    """
    Record a security event. If `db` is provided, writes to the DB table
    and logs at DEBUG. If the DB write fails (or db is None), logs at WARNING
    so the event is never silently dropped.
    """
    log_msg = (
        f"security_event | type={event_type} endpoint={endpoint} "
        f"field={field_name} user={user_id} {extra}"
    )

    if db is not None:
        try:
            from app.db.crud import log_security_event
            await log_security_event(
                db,
                endpoint=endpoint,
                field_name=field_name,
                event_type=event_type,
                user_id=user_id,
            )
            await db.commit()
            logger.debug(log_msg)
            return
        except Exception as exc:
            logger.warning("%s | db_write_failed=%s", log_msg, exc)
            return

    # No DB available — ensure the event still appears in logs
    logger.warning(log_msg)
