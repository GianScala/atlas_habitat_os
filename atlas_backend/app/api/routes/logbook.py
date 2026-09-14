"""The crew's meter log: writing readings down, and reading the analysis back.

Sits under `/api/mission` with the plan, because it is measured over the
mission's own days and is meaningless without one. Kept in its own module
because it shares no arithmetic with the plan whatsoever: the plan is about
ceilings nobody measured, and this is about dials somebody read.

No habitat database is touched by anything here. That is the point — the log is
the independent account the Grafana figures get checked against, and it stays
available on exactly the day the telemetry does not.
"""


from fastapi import APIRouter, HTTPException

from app.core.errors import AtlasError
from app.mission import logbook as book
from app.mission import repository as repo
from app.schemas.logbook import Logbook, ReadingWrite

router = APIRouter(prefix="/mission/log", tags=["mission"])


def _refuse(exc: AtlasError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


def _payload() -> Logbook:
    return Logbook(**book.build_logbook(repo.load_plan(), repo.load_readings()))


@router.get("", response_model=Logbook)
def read_log() -> Logbook:
    """The sheet, the consumption derived from it, and how it distributes."""
    try:
        return _payload()
    except AtlasError as exc:
        raise _refuse(exc) from exc


@router.put("/reading", response_model=Logbook)
def write_reading(body: ReadingWrite) -> Logbook:
    """Record one meter reading, or clear the box by sending a null value.

    The WHOLE log comes back rather than the one box, for the same reason the
    extras endpoints return the whole plan: one reading closes the block before
    it and opens the block after it, so a response carrying only the row that
    changed would leave two days on screen derived from readings that no longer
    exist.
    """
    try:
        plan = repo.load_plan()
        meter = book.check_meter(body.resource, body.meter)
        slot = book.check_slot(body.resource, body.slot)
        day = book.check_day(body.day_index, plan.mission)
        value = book.check_value(body.value, meter)

        if value is None:
            repo.delete_reading(meter.resource, meter.key, day, slot)
        else:
            repo.save_reading(meter.resource, meter.key, day, slot, value)

        return _payload()
    except AtlasError as exc:
        raise _refuse(exc) from exc


@router.post("/clear", response_model=Logbook)
def clear_log(resource: str | None = None) -> Logbook:
    """Forget the meter log — one resource's rounds, or every one of them.

    Deliberately not part of resetting the mission plan. These are readings
    somebody walked the habitat to take; re-declaring a mission does not make
    them untrue, and deleting them has to be a thing a person decided to do.
    """
    try:
        if resource is not None:
            book.check_resource(resource)
        repo.clear_readings(resource)
        return _payload()
    except AtlasError as exc:
        raise _refuse(exc) from exc
