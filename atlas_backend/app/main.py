"""Application factory and entry point.

    uvicorn app.main:app --reload
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.routes import api_router
from app.config import get_settings
from app.core.errors import AtlasError
from app.core.http_security import RequestGuard
from app.core.logging import configure_logging, get_logger
from app.habitat import profile as habitat_profile
from app.llm import inventory, selection, warm
from app.storage.database import initialise

log = get_logger(__name__)

DESCRIPTION = """
Natural-language questions about analog space habitat telemetry using read-only
data-source adapters. Answers are instructed to cite queried sources; model
output remains fallible and needs independent verification.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Prepare storage, log the configuration we booted with, then serve."""
    settings = get_settings()
    log.info("ATLAS backend starting")

    initialise()

    choice = selection.active(settings)
    log.info("  model:      %s on %s", choice.model, choice.provider)
    if choice.local:
        log.info("  ollama:     %s", settings.ollama_base)
    log.info("  data source:%s", settings.datasource_summary)
    log.info("  habitat:    %s", habitat_profile().name)

    ready, detail = inventory.quick_check(settings)
    if not ready:
        log.warning("No model ready — %s", detail)
    if not settings.datasource_configured:
        log.warning(
            "Data source not fully configured — telemetry queries will fail."
        )

    # Backgrounded, and deliberately not awaited: the point is that the prefill
    # happens while the crew is still opening the page, not that the server
    # waits for it. Only worth starting if there is a model to warm.
    if ready:
        warm.warm(settings)

    yield
    log.info("ATLAS backend stopped")


def create_app() -> FastAPI:
    """Build the application. Kept a function so tests can make their own."""
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="ATLAS",
        description=DESCRIPTION,
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type"],
    )

    app.add_middleware(
        RequestGuard,
        origins=settings.cors_origin_list,
        max_body_bytes=(settings.max_upload_mb + 1) * 1024 * 1024,
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=[
            host.strip() for host in settings.allowed_hosts.split(",") if host.strip()
        ],
    )

    @app.exception_handler(AtlasError)
    async def handle_atlas_error(request: Request, exc: AtlasError) -> JSONResponse:
        """Our own failures carry a reason worth showing the person."""
        log.warning("%s on %s: %s", type(exc).__name__, request.url.path, exc.message)
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message, "kind": type(exc).__name__},
        )

    app.include_router(api_router, prefix="/api")
    return app


app = create_app()


def main() -> int:
    """Run the development server: `python -m app.main`."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
        log_level=settings.log_level.lower(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
