"""Shapes for the mission-plan endpoints.

Mirrored in `atlas_frontend/src/lib/types.ts`. This file is the source of
truth: FastAPI drops any key the response model does not declare, silently, so
a field added to the service and forgotten here never reaches the browser and
never fails a test that stops at the service layer.
"""


from pydantic import BaseModel


class MissionWindow(BaseModel):
    """When the mission runs, and where in it we are right now."""

    is_declared: bool = False
    name: str = ""
    start: str | None = None
    end: str | None = None
    days: int | None = None
    # before | running | after
    state: str = "before"
    # Which mission day today is, or None outside the mission.
    day_index: int | None = None
    day_code: str | None = None
    days_elapsed: int = 0
    days_remaining: int | None = None
    elapsed_fraction: float = 0.0
    cycle_number: int | None = None
    cycle_first: int | None = None
    cycle_last: int | None = None
    # The habitat's calendar date, which is not always the machine's.
    today: str = ""


class ExtraEntry(BaseModel):
    """One piece of planned consumption the flat daily rate does not cover."""

    id: str
    resource: str
    label: str
    amount: float
    # once | daily
    kind: str = "once"
    on_date: str | None = None
    mission_day: int | None = None
    day_code: str | None = None
    note: str = ""
    # True where the mission's dates have moved out from under it, so it now
    # comes out of no day's allowance.
    stranded: bool = False
    updated_at: float = 0.0


class ExtraWrite(BaseModel):
    """An extra as the interface sends it.

    A one-off may name either a mission day or a calendar date; the backend
    resolves whichever was given, because both are how a crew talks about the
    same afternoon.
    """

    resource: str
    label: str
    amount: float
    kind: str = "once"
    on_date: str | None = None
    mission_day: int | None = None
    note: str = ""


class PlanResource(BaseModel):
    """One resource in the plan editor."""

    key: str
    label: str
    unit: str = ""
    # The most that may be drawn across the whole mission, or None where the
    # crew has not capped it.
    total: float | None = None
    # "crew" or "default" — a default is a starting point we shipped, and the
    # interface says so wherever a figure derives from one.
    source: str = "default"
    # A ceiling to offer in the setup form: the shipped daily figure across the
    # declared length. Never stored, and never used in any arithmetic.
    suggested_total: float | None = None
    suggested_daily: float | None = None
    extras: list[ExtraEntry] = []


class MissionPlan(BaseModel):
    """The plan as it stands, for the editor."""

    day_start_offset_minutes: int
    day_start_label: str
    mission: MissionWindow
    updated_at: float | None = None
    is_all_default: bool = True
    default_note: str = ""
    warnings: list[str] = []
    resources: list[PlanResource] = []


class PlanUpdate(BaseModel):
    """A change to the plan. Every field is optional; absent means unchanged.

    `totals` is resource -> ceiling for the whole mission. A resource left out
    keeps what it had, so one can be saved without sending the whole plan back
    and overwriting an edit made in another tab.
    """

    name: str | None = None
    start: str | None = None
    days: int | None = None
    totals: dict[str, float | None] | None = None
    day_start_offset_minutes: int | None = None


class PlannedDay(BaseModel):
    """One mission day on the calendar."""

    index: int
    # MD-07.
    code: str
    date: str
    start: str
    # past | today | future
    state: str
    # What the original plan allowed: the flat rate plus this day's extras.
    planned: float
    # What the forward plan now allows. None on a day already behind us.
    revised: float | None = None
    extras: float = 0.0
    extra_labels: list[str] = []
    # What the meters say was drawn. None is a day they did not cover.
    actual: float | None = None
    variance: float | None = None
    # over | under | on_plan | no_data | pending
    status: str = "pending"
    # False on a day older than the lookback window, which was never asked
    # about — a different thing from a day the sensors missed.
    queried: bool = True


class Budget(BaseModel):
    """One resource measured against one window of the day plan."""

    horizon: str
    label: str
    days: int
    period_start: str
    period_end: str
    first_code: str | None = None
    last_code: str | None = None
    # How much of the window has passed, 0…1.
    elapsed_fraction: float
    used: float | None = None
    # The original plan's allowance across this window.
    target: float | None = None
    # What the forward plan now allows across it, after re-spreading what is
    # left over the days that remain.
    revised_target: float | None = None
    extras: float = 0.0
    source: str = "default"
    # How much of the allowance is gone, 0…1. The "we are at 80%" figure.
    used_fraction: float | None = None
    # What the plan itself expected by this moment — extras on their own days,
    # not smeared across the window.
    planned_by_now: float | None = None
    remaining: float | None = None
    # Where this window lands at the current rate. Absent early on, where a
    # rate read from a few minutes means nothing.
    projected: float | None = None
    # used / planned_by_now. Above 1 is spending faster than the plan intended.
    pace_ratio: float | None = None
    # nominal | caution | over | unset | no_data
    status: str = "nominal"
    days_covered: int = 0
    days_expected: int = 0
    note: str | None = None


class ResourceTracking(BaseModel):
    key: str
    label: str
    noun: str
    unit: str = ""
    unit_source: str = "unknown"
    measurement: str
    field: str
    query: str = ""

    # -- the declaration ---------------------------------------------------
    total: float | None = None
    source: str = "default"

    # -- the plan ----------------------------------------------------------
    # The allowance an ordinary day gets: the ceiling less every extra, spread
    # over the mission.
    flat_per_day: float | None = None
    # What an ordinary day gets from here on, after re-spreading what is left.
    revised_per_day: float | None = None
    extras_total: float = 0.0
    extras_to_come: float = 0.0

    # -- where we are ------------------------------------------------------
    consumed: float | None = None
    remaining: float | None = None
    days_measured: int = 0
    days_uncovered: int = 0
    # False where the extras still scheduled cost more than what is left.
    feasible: bool = True
    shortfall: float = 0.0

    budgets: list[Budget] = []
    days: list[PlannedDay] = []
    extras: list[ExtraEntry] = []
    notes: list[str] = []
    # Set when this resource alone could not be read; the other still renders.
    error: str | None = None


class Tracking(BaseModel):
    """Everything the mission page draws."""

    generated_at: str
    day_start_offset_minutes: int
    day_start_label: str
    mission: MissionWindow
    plan_updated_at: float | None = None
    plan_is_all_default: bool = True
    default_note: str = ""
    warnings: list[str] = []
    resources: list[ResourceTracking] = []
