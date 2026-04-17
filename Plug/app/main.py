"""
Voice AI Smart Relay Controller — main FastAPI application.

Wires together:
  - Application lifespan (GPIO startup / shutdown)
  - CORS middleware
  - Rate-limiting via slowapi
  - Global exception handlers
  - Routers: /command, /status
  - JSON structured logging with per-request request_id injection
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from app.config import get_settings
from app.routes.command import router as command_router
from app.routes.status import router as status_router
from app.services.relay_service import shutdown_gpio, startup_gpio
from app.utils.exceptions import RelayControllerError
from app.utils.logger import get_logger, get_request_id, set_request_id

settings = get_settings()
logger = get_logger("relay_controller.main")

# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[f"{settings.rate_limit_per_minute}/minute"],
)


# ---------------------------------------------------------------------------
# Lifespan context manager
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:  # noqa: ARG001
    """
    Manage application startup and shutdown.

    **Startup**: Initialise GPIO pins and set all relays to OFF.
    **Shutdown**: Set all relays to OFF and release GPIO resources.
    """
    logger.info(
        {
            "event": "startup",
            "environment": settings.environment,
            "gpio_pins": settings.gpio_pins_bcm,
            "rate_limit": settings.rate_limit_per_minute,
        }
    )
    startup_gpio(settings)
    yield
    # Shutdown
    logger.info({"event": "shutdown"})
    shutdown_gpio()


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Voice AI Smart Relay Controller",
    description=(
        "Production-ready backend for controlling 8 physical relays "
        "via voice commands (Whisper + Gemini), text, or manual input."
    ),
    version="1.0.0",
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
    openapi_url="/openapi.json" if not settings.is_production else None,
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Middleware: rate limiting
# ---------------------------------------------------------------------------

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
app.add_middleware(SlowAPIMiddleware)

# ---------------------------------------------------------------------------
# Middleware: CORS
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if not settings.is_production else [],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Middleware: inject request_id into every async context
# ---------------------------------------------------------------------------

@app.middleware("http")
async def request_id_middleware(request: Request, call_next) -> Response:
    """Attach a unique request_id to every incoming HTTP request."""
    rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    set_request_id(rid)

    logger.debug(
        {
            "event": "request_start",
            "method": request.method,
            "path": request.url.path,
            "client_ip": request.client.host if request.client else "unknown",
            "request_id": rid,
        }
    )

    response = await call_next(request)
    response.headers["X-Request-ID"] = rid

    logger.debug(
        {
            "event": "request_end",
            "status_code": response.status_code,
            "request_id": rid,
        }
    )
    return response


# ---------------------------------------------------------------------------
# Global exception handlers
# ---------------------------------------------------------------------------

@app.exception_handler(RelayControllerError)
async def relay_controller_exception_handler(
    request: Request,  # noqa: ARG001
    exc: RelayControllerError,
) -> JSONResponse:
    """Convert all custom application exceptions to a uniform JSON error body."""
    logger.error(
        {
            "event": "handled_exception",
            "error_code": exc.error_code,
            "message": exc.message,
            "request_id": get_request_id(),
        }
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.error_code,
            "message": exc.message,
            "request_id": get_request_id(),
            "detail": exc.detail if not settings.is_production else None,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,  # noqa: ARG001
    exc: RequestValidationError,
) -> JSONResponse:
    """Return a consistent 422 envelope for Pydantic / FastAPI validation errors."""
    logger.warning(
        {
            "event": "validation_error",
            "errors": exc.errors(),
            "request_id": get_request_id(),
        }
    )
    return JSONResponse(
        status_code=422,
        content={
            "error": "validation_error",
            "message": "Request validation failed.",
            "request_id": get_request_id(),
            "detail": jsonable_encoder(exc.errors()) if not settings.is_production else None,
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(
    request: Request,  # noqa: ARG001
    exc: Exception,
) -> JSONResponse:
    """Catch-all for unexpected errors — never expose internal details in production."""
    logger.exception(
        {
            "event": "unhandled_exception",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "request_id": get_request_id(),
        }
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "message": "An unexpected error occurred. Please try again later.",
            "request_id": get_request_id(),
            "detail": str(exc) if not settings.is_production else None,
        },
    )


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(command_router, prefix="")
app.include_router(status_router, prefix="")


# ---------------------------------------------------------------------------
# Static files — serve voice_test.html at /test
# ---------------------------------------------------------------------------

import os as _os
_static_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
app.mount("/static", StaticFiles(directory=_static_dir), name="static")


@app.get("/test", response_class=HTMLResponse, include_in_schema=False)
async def voice_test_page() -> HTMLResponse:
    """Serve the browser-based voice recorder test page."""
    html_path = _os.path.join(_static_dir, "voice_test.html")
    with open(html_path, encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


# ---------------------------------------------------------------------------
# Health-check (not rate-limited)
# ---------------------------------------------------------------------------

@app.get("/health", include_in_schema=False)
async def health_check() -> dict:
    """Lightweight liveness probe for load-balancers and containers."""
    return {"status": "ok", "service": "relay-controller"}


# ---------------------------------------------------------------------------
# Entry-point for direct execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        reload=not settings.is_production,
    )
