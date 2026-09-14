"""Dashboard data: the same telemetry the chat reads, shaped for charts."""

from fastapi import APIRouter, HTTPException, Query

from app.core.errors import AtlasError
from app.schemas.dashboard import Dashboard, RangeOption
from app.services.dashboard import build_dashboard
from app.telemetry.timeseries import RANGE_LABELS, RANGES

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/ranges", response_model=list[RangeOption])
def ranges() -> list[RangeOption]:
    """The selectable windows, in order, shortest first."""
    return [
        RangeOption(
            key=key,
            label=RANGE_LABELS.get(key, key),
            minutes=minutes,
            bucket_minutes=bucket,
        )
        for key, (minutes, bucket) in RANGES.items()
    ]


@router.get("", response_model=Dashboard)
def dashboard(
    range: str = Query(default="24h", description="One of the keys from /ranges."),
    panels: str = Query(
        default="",
        description="Optional comma-separated panel ids, to refresh a subset.",
    ),
) -> Dashboard:
    """Every panel for a time range.

    A single failing panel is reported on that panel rather than failing the
    request — a broken sensor should leave a gap, not an error screen.
    """
    wanted = [p.strip() for p in panels.split(",") if p.strip()] or None

    try:
        return Dashboard(**build_dashboard(range, wanted))
    except AtlasError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
