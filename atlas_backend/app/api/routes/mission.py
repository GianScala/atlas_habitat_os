"""The mission plan: declaring it, editing it, and tracking against it."""

from datetime import UTC, date, datetime

from fastapi import APIRouter, HTTPException

from app.core.errors import AtlasError
from app.mission import repository as repo
from app.mission import tracking as track
from app.mission.meters import METERS_BY_KEY
from app.mission.periods import local_date, offset_label
from app.mission.plan import (
    RESOURCES,
    Plan,
    normalise_offset,
    validate_extra,
    validate_mission,
    validate_total,
)
from app.schemas.mission import (
    ExtraEntry,
    ExtraWrite,
    MissionPlan,
    MissionWindow,
    PlanResource,
    PlanUpdate,
    Tracking,
)

router = APIRouter(prefix="/mission", tags=["mission"])


def _as_schema(plan: Plan) -> MissionPlan:
    """A stored plan in the shape the editor wants it."""
    mission = plan.mission
    end = mission.end

    return MissionPlan(
        day_start_offset_minutes=plan.day_start_offset_minutes,
        day_start_label=f"00:00 {offset_label(plan.day_start_offset_minutes)}",
        mission=MissionWindow(
            is_declared=mission.is_declared,
            name=mission.name,
            start=None if mission.start is None else mission.start.isoformat(),
            end=None if end is None else end.isoformat(),
            days=mission.days,
            # The habitat's date, not the browser's. The setup form offers it
            # as the start of an undeclared mission, and a crew two hours ahead
            # of the machine running this should be offered their own today.
            today=_today(plan).isoformat(),
        ),
        updated_at=plan.updated_at,
        is_all_default=plan.is_all_default,
        default_note=plan.default_note,
        warnings=list(plan.warnings),
        resources=[
            PlanResource(
                key=key,
                label=label,
                # The unit belongs to the instrument, not to the plan — the
                # editor prints it beside the input so nobody has to guess
                # whether a water ceiling is litres or cubic metres.
                unit=_unit_for(key),
                total=plan.total(key),
                source=plan.source(key),
                suggested_total=plan.suggested_total(key),
                suggested_daily=plan.suggested_daily.get(key),
                extras=[_extra_entry(extra, plan) for extra in plan.extras_for(key)],
            )
            for key, label in RESOURCES.items()
        ],
    )


def _today(plan: Plan) -> date:
    """The habitat's calendar date right now."""
    return local_date(datetime.now(UTC), plan.day_start_offset_minutes)


def _extra_entry(extra, plan: Plan) -> ExtraEntry:
    index = plan.mission.day_index(extra.on_date) if extra.on_date else None
    inside = extra.on_date is not None and plan.mission.contains(extra.on_date)
    return ExtraEntry(
        id=extra.id,
        resource=extra.resource,
        label=extra.label,
        amount=extra.amount,
        kind=extra.kind,
        on_date=None if extra.on_date is None else extra.on_date.isoformat(),
        mission_day=index if inside else None,
        day_code=None if not inside or index is None else f"MD-{index:02d}",
        note=extra.note,
        stranded=extra.on_date is not None and not inside,
        updated_at=extra.updated_at,
    )


def _unit_for(resource: str) -> str:
    """The unit of the gauge behind a resource, or empty if it has none."""
    from app.telemetry.units import unit_for

    meter = METERS_BY_KEY.get(resource)
    if meter is None:
        return ""
    unit, source = unit_for(meter.measurement, meter.field)
    return unit if source == "known" else ""


def _refuse(exc: AtlasError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("/plan", response_model=MissionPlan)
def read_plan() -> MissionPlan:
    """The mission as declared, its ceilings, and its extras."""
    try:
        return _as_schema(repo.load_plan())
    except AtlasError as exc:
        raise _refuse(exc) from exc


@router.put("/plan", response_model=MissionPlan)
def update_plan(body: PlanUpdate) -> MissionPlan:
    """Declare or change the mission.

    Everything is validated before anything is written, so a body with one bad
    figure in it leaves the stored plan exactly as it was rather than half
    applied.
    """
    try:
        current = repo.load_plan()

        # The mission's three facts move together or not at all. A start
        # without a length is not half a mission, it is no mission, and
        # storing it would leave the page unable to say which.
        mission = None
        wants_mission = any(
            value is not None for value in (body.name, body.start, body.days)
        )
        if wants_mission:
            start = body.start if body.start is not None else _iso(current.mission.start)
            days = body.days if body.days is not None else current.mission.days
            name = body.name if body.name is not None else current.mission.name
            if start is None or days is None:
                raise AtlasError(
                    "A mission needs both a first day and a length. Give the "
                    "start date and how many days it runs, and every day's "
                    "allowance follows from those and the ceilings."
                )
            mission = validate_mission(name, start, days)

        checked: dict[str, float | None] = {}
        for resource, value in (body.totals or {}).items():
            checked[resource] = validate_total(resource, value)

        offset = (
            None
            if body.day_start_offset_minutes is None
            else normalise_offset(body.day_start_offset_minutes)
        )

        if mission is not None:
            repo.save_mission(mission)
        if checked:
            repo.save_totals(checked)
        if offset is not None:
            repo.save_day_start(offset)

        return _as_schema(repo.load_plan())
    except AtlasError as exc:
        raise _refuse(exc) from exc


def _iso(value) -> str | None:
    return None if value is None else value.isoformat()


@router.post("/plan/reset", response_model=MissionPlan)
def reset_plan() -> MissionPlan:
    """Forget the mission, every ceiling, and every extra."""
    try:
        repo.reset_plan()
        return _as_schema(repo.load_plan())
    except AtlasError as exc:
        raise _refuse(exc) from exc


# -- extras ----------------------------------------------------------------


@router.post("/extras", response_model=MissionPlan)
def add_extra(body: ExtraWrite) -> MissionPlan:
    """Book a piece of planned consumption onto a mission day, or onto all of them.

    The whole plan comes back rather than the one row, because adding an extra
    moves every other day's allowance — the ceiling did not change, so what is
    left for an ordinary day did.
    """
    try:
        plan = repo.load_plan()
        repo.add_extra(validate_extra(body.model_dump(), plan.mission))
        return _as_schema(repo.load_plan())
    except AtlasError as exc:
        raise _refuse(exc) from exc


@router.put("/extras/{extra_id}", response_model=MissionPlan)
def edit_extra(extra_id: str, body: ExtraWrite) -> MissionPlan:
    """Change one extra."""
    try:
        plan = repo.load_plan()
        repo.update_extra(extra_id, validate_extra(body.model_dump(), plan.mission))
        return _as_schema(repo.load_plan())
    except AtlasError as exc:
        raise _refuse(exc) from exc


@router.delete("/extras/{extra_id}", response_model=MissionPlan)
def remove_extra(extra_id: str) -> MissionPlan:
    """Drop one extra. Its amount goes back into every other day's allowance."""
    try:
        repo.delete_extra(extra_id)
        return _as_schema(repo.load_plan())
    except AtlasError as exc:
        raise _refuse(exc) from exc


# -- tracking --------------------------------------------------------------


@router.get("/tracking", response_model=Tracking)
def tracking() -> Tracking:
    """The day plan, what was actually drawn, and what the days ahead now allow.

    Re-derived on every read rather than stored: the forward plan is a function
    of the meters, and a cached one would be a plan for a habitat that no
    longer exists.

    A resource that could not be read is reported on that resource rather than
    failing the request — a broken water gauge should not take the power plan
    off the page with it.
    """
    try:
        return Tracking(**track.build_tracking(repo.load_plan()))
    except AtlasError as exc:
        raise _refuse(exc) from exc
