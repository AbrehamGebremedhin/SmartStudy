import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from app.api.routes import chat, evaluation, flashcards, history, mcq, notes
from app.config import settings
from app.core.exceptions import OutOfContextError
from app.db.database import Base, engine, get_db
from app.logging_config import configure_logging
from app.security.audit import INJECTION_ATTEMPT, RATE_LIMIT_EXCEEDED, record
from app.security.headers import SecurityHeadersMiddleware
from app.security.rate_limiter import limiter

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Eagerly init the generation agent singleton and pre-warm the Ollama embedding
    # model so the first real request doesn't pay the cold-load penalty (~25 s).
    try:
        from app.services.generation import get_agent
        _agent = get_agent()
        await _agent.context_agent.retrieval_agent.embeddings.aembed_query("warmup")
        logger.info("Ollama embedding model warmed up")
    except Exception as _e:
        logger.warning("Ollama warmup skipped (Ollama may not be running): %s", _e)
    yield
    await engine.dispose()


app = FastAPI(
    title="SmartStudy API",
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter

# Security headers — must be added before CORS so it runs on every response
app.add_middleware(SecurityHeadersMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Requested-With"],
)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Log rate limit violations and return 429."""
    async for db in get_db():
        await record(
            event_type=RATE_LIMIT_EXCEEDED,
            endpoint=str(request.url.path),
            field_name="",
            extra=f"limit={exc.detail}",
            db=db,
        )
        break
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"detail": "Rate limit exceeded. Please slow down."},
    )


@app.exception_handler(OutOfContextError)
async def out_of_context_handler(request: Request, exc: OutOfContextError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "out_of_context",
            "message": exc.message,
            "valid_options": exc.valid_options,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Log injection-detection errors; return a generic 422 for all validation failures."""
    for error in exc.errors():
        if error.get("msg") == "Value error, Invalid input detected.":
            field = ".".join(str(p) for p in error.get("loc", []))
            async for db in get_db():
                await record(
                    event_type=INJECTION_ATTEMPT,
                    endpoint=str(request.url.path),
                    field_name=field,
                    db=db,
                )
                break
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": "Invalid input."},
    )


app.include_router(mcq.router, prefix="/api")
app.include_router(flashcards.router, prefix="/api")
app.include_router(notes.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(history.router, prefix="/api")
app.include_router(evaluation.router, prefix="/api")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
