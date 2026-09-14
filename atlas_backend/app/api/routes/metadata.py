"""Read-only metadata the interface uses to orient a new user.

None of this answers a telemetry question — it populates the empty state and
the zone reference, so someone opening the app knows what they can ask.
"""

from fastapi import APIRouter, HTTPException

from app.core.errors import AtlasError
from app.schemas.telemetry import MeasurementList, SuggestedQuestion, ZoneInfo
from app.telemetry.discovery import list_measurements, reset_cache
from app.telemetry.zones import ZONE_NAMES

router = APIRouter(prefix="/meta", tags=["metadata"])

# Deliberately spread across the tool surface: a point reading, an aggregate,
# a consumption question, and a discovery question.
SUGGESTED_QUESTIONS = [
    SuggestedQuestion(
        label="Current conditions",
        question="What are the latest room conditions available in this habitat?",
    ),
    SuggestedQuestion(
        label="Power draw",
        question="Which electrical readings are available, and what do they show?",
    ),
    SuggestedQuestion(
        label="Water use",
        question="Can the telemetry show clean water use over the last 3 days?",
    ),
    SuggestedQuestion(
        label="What's monitored",
        question="What can you tell me about the habitat? Which sensors are reporting?",
    ),
]


@router.get("/measurements", response_model=MeasurementList)
def measurements() -> MeasurementList:
    """Every habitat measurement, discovered live from the database."""
    try:
        found = list_measurements()
    except AtlasError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    return MeasurementList(
        measurements=found["data"] or [],
        count=found["count"],
        note=found.get("note"),
    )


@router.get("/zones", response_model=list[ZoneInfo])
def zones() -> list[ZoneInfo]:
    """How database tag values map to the names people actually use."""
    return [ZoneInfo(tag=tag, name=name) for tag, name in ZONE_NAMES.items()]


@router.get("/suggestions", response_model=list[SuggestedQuestion])
def suggestions() -> list[SuggestedQuestion]:
    """Starter questions for the empty chat screen."""
    return SUGGESTED_QUESTIONS


@router.post("/refresh", response_model=MeasurementList)
def refresh() -> MeasurementList:
    """Re-read the schema.

    The schema is cached for the life of the process. Call this after a sensor
    is added so the model can see it without a restart.
    """
    reset_cache()
    return measurements()
