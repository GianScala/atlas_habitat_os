"""Health and readiness.

`/health` is cheap and never touches the network. `/health/datasource` runs a
real query and asks the local model runtime whether it is up, because "the
process is up", "the habitat data is reachable" and "a model is loaded and
able to answer" are three different claims and the interface needs all three.
"""

from fastapi import APIRouter, Depends

from app.api.deps import get_app_settings
from app.config import Settings
from app.core.errors import AtlasError
from app.core.logging import get_logger
from app.llm import inventory, selection
from app.schemas.telemetry import HealthStatus
from app.telemetry.discovery import discover

log = get_logger(__name__)

router = APIRouter(tags=["health"])


def _base(settings: Settings) -> HealthStatus:
    """What we can say without asking anything else."""
    choice = selection.active(settings)
    return HealthStatus(
        status="ok",
        provider=choice.provider,
        model=choice.model,
        model_label=(
            f"{choice.model} (local)" if choice.local else f"{choice.model} (Anthropic)"
        ),
        local=choice.local,
        datasource_configured=settings.datasource_configured,
    )


@router.get("/health", response_model=HealthStatus)
def health(settings: Settings = Depends(get_app_settings)) -> HealthStatus:
    """Is the service configured and running? No network calls."""
    return _base(settings)


@router.get("/health/datasource", response_model=HealthStatus)
def datasource_health(settings: Settings = Depends(get_app_settings)) -> HealthStatus:
    """Can we reach the habitat database, and is a model ready to answer?"""
    status = _base(settings)
    status.model_ready, status.model_detail = inventory.quick_check(settings)

    try:
        found = discover()
    except AtlasError as exc:
        log.warning("Datasource health check failed: %s", exc.message)
        status.status = "degraded"
        status.datasource_ok = False
        status.datasource_detail = exc.message
        return status

    status.datasource_ok = True
    status.measurement_count = len(found["habitat"])
    status.datasource_detail = (
        f"{len(found['habitat'])} habitat measurements "
        f"({found['internal_count']} internal metrics filtered out)"
    )
    return status
