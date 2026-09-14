"""The plan: a mission, a ceiling per resource, and the extras on top.

WHAT THE CREW DECLARES is deliberately small — the day the mission starts, how
many days it runs, and the most of each resource it may consume from end to
end. Three facts. Everything else on the mission page is derived from them by
`dayplan.py`, because everything else is arithmetic, and arithmetic a crew has
to do by hand is arithmetic that goes wrong at 02:00 on day nineteen.

Until those three are given there is no plan, only figures this repository
shipped, and the interface says exactly that rather than drawing a percentage
of a budget nobody agreed to.

THE HORIZONS are three views of the SAME ceiling, not three budgets: today,
this three-day cycle, and the mission. They are consistent by construction —
each is a sum over the day plan — which is the point of deriving them. The old
arrangement let a crew set 150 a day and 1050 a week and then wonder which of
the two the page believed.

The three-day cycles are counted from the mission's first day, so cycle 1 is
MD-01 to MD-03. Three days is not a calendar unit and needs a day to be counted
from; the mission's own start is the only honest candidate.

THE EXTRAS are planned consumption the flat rate does not cover: the water an
experiment takes on MD-14, the power the dishwasher draws every day. They are
part of the plan, not a deviation from it, so they are carved OUT of the
mission ceiling and placed on the days they fall on — which lowers every other
day rather than raising the total. A ceiling that grew every time someone
remembered an experiment would not be a ceiling.

PROVENANCE. Every figure is either the crew's or a default this repository
shipped, and the two are never blended. A default is a starting point for an
argument, and a figure derived from one is labelled all the way to the screen.
The mechanism is deliberately dumb: a row in the database is the crew's, and
its absence is the default. There is no third state to get out of step.

THE DAY BOUNDARY. "Today" needs a midnight, and UTC's is not usually the
habitat's. The plan carries the offset from UTC in whole hours — whole,
because consumption is attributed in hourly buckets at best, and a half-hour
offset would leave half an hour of use on either side of midnight with no way
to say which side it belonged on.
"""

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from app.core.errors import AtlasError


@dataclass(frozen=True)
class Horizon:
    """One window the day plan is summed over for a card."""

    key: str
    label: str
    # How many days it covers, or None where it covers the whole mission — a
    # length that is not known until the crew declares one.
    days: int | None

    @property
    def spans_mission(self) -> bool:
        return self.days is None


# The keys are the wire contract; the labels title a card. Ordered shortest
# first, which is the order a crew reads them in: where are we today, where are
# we this cycle, where are we overall.
HORIZONS: dict[str, Horizon] = {
    "day": Horizon("day", "Today", 1),
    "cycle": Horizon("cycle", "This 3-day cycle", 3),
    "mission": Horizon("mission", "Whole mission", None),
}

CYCLE_DAYS = 3

# Resource key -> label. Which resources a mission budgets, and what telemetry
# reads each one, is habitat-specific, so it comes from the habitat profile's
# `mission_resources:` section (the telemetry mapping itself lives in
# `meters.py`, which reads the same section). A plan can still be edited and
# validated without touching the database.
def _resources_from_profile() -> dict[str, str]:
    from app.habitat import profile

    return {
        str(r["key"]): str(r.get("label", r["key"]))
        for r in profile().mission_resources
        if r.get("key")
    }


# Resolved once at import, like the rest of the habitat profile — a habitat does
# not change which resources it budgets mid-session.
RESOURCES: dict[str, str] = _resources_from_profile()

# Whole hours, and no further from UTC than any real place is.
MIN_OFFSET_MINUTES = -12 * 60
MAX_OFFSET_MINUTES = 14 * 60

# A ceiling is a quantity, so it cannot be negative. Zero is allowed and means
# something specific — "we plan to draw none" — which is a real plan for a
# resource under embargo, and reads as over budget the moment any is drawn.
MAX_TOTAL = 10_000_000.0

# The longest mission this page will lay out day by day. Not a limit on what a
# habitat can do — a limit on what a table of one row per day stays readable
# at, and on what fits in one response without paging.
MAX_MISSION_DAYS = 400
MIN_MISSION_DAYS = 1

MAX_NAME = 120
MAX_LABEL = 80
MAX_NOTE = 400

# How an extra recurs. Two kinds, because two are what a crew actually plans:
# a thing that happens once on a known day, and a thing that happens daily.
ONCE = "once"
DAILY = "daily"
EXTRA_KINDS = (ONCE, DAILY)

CREW = "crew"
DEFAULT = "default"

_DEFAULTS_FILE = Path(__file__).with_name("default_plan.json")


def day_code(index: int) -> str:
    """`MD-07` — how a mission day is named everywhere it is shown."""
    return f"MD-{index:02d}"


@dataclass(frozen=True)
class Mission:
    """The frame: when the mission starts, how long it runs, what it is called."""

    name: str = ""
    start: date | None = None
    # Days from MD-01 to the last day, both counted.
    days: int | None = None

    @property
    def is_declared(self) -> bool:
        """Has the crew said when this mission runs and for how long?

        Both, or neither. A start with no length cannot be paced against and
        would produce a mission card measuring a share of an unknown whole, so
        a half-filled mission is treated as no mission at all.
        """
        return self.start is not None and self.days is not None and self.days > 0

    @property
    def end(self) -> date | None:
        """The last day of the mission, included."""
        if not self.is_declared:
            return None
        assert self.start is not None and self.days is not None
        return self.start + timedelta(days=self.days - 1)

    def day_index(self, day: date) -> int | None:
        """Which mission day a calendar date is, counting MD-01 as 1."""
        if self.start is None:
            return None
        return (day - self.start).days + 1

    def date_of(self, index: int) -> date | None:
        if self.start is None:
            return None
        return self.start + timedelta(days=index - 1)

    def contains(self, day: date) -> bool:
        end = self.end
        if self.start is None or end is None:
            return False
        return self.start <= day <= end

    def dates(self) -> list[date]:
        """Every calendar date in the mission, MD-01 first."""
        if not self.is_declared:
            return []
        assert self.start is not None and self.days is not None
        return [self.start + timedelta(days=n) for n in range(self.days)]


@dataclass(frozen=True)
class Extra:
    """Planned consumption the flat daily rate does not cover."""

    id: str
    resource: str
    label: str
    amount: float
    # ONCE (on `on_date`) or DAILY (every day of the mission).
    kind: str
    on_date: date | None = None
    note: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0

    @property
    def resource_label(self) -> str:
        return RESOURCES.get(self.resource, self.resource)

    def falls_on(self, day: date, mission: Mission) -> bool:
        """Does this extra put consumption on that particular day?"""
        if not mission.contains(day):
            return False
        if self.kind == DAILY:
            return True
        return self.on_date == day

    def describe(self, mission: Mission) -> str:
        """The entry in one line, for a log, a tooltip, or a prompt."""
        if self.kind == DAILY:
            when = "every mission day"
        elif self.on_date is None:
            when = "on an unrecorded day"
        else:
            index = mission.day_index(self.on_date)
            when = (
                f"on {day_code(index)} ({self.on_date.isoformat()})"
                if index is not None and mission.contains(self.on_date)
                else f"on {self.on_date.isoformat()}, outside the mission"
            )
        return f"{self.label} — {self.amount:g} of {self.resource} {when}"


@dataclass(frozen=True)
class Plan:
    """The ceiling per resource, the mission it applies to, and the extras."""

    # resource -> the most that may be consumed across the whole mission, or
    # None where nobody has set one.
    totals: dict[str, float | None]
    # resource -> CREW | DEFAULT. Parallel to `totals`.
    sources: dict[str, str]
    day_start_offset_minutes: int
    mission: Mission = field(default_factory=Mission)
    extras: tuple[Extra, ...] = ()
    # Per-resource daily figures this repository shipped. Not a plan — the
    # numbers the setup form multiplies by the duration to offer a starting
    # ceiling, so a crew types a length and sees a plausible total rather than
    # an empty box.
    suggested_daily: dict[str, float | None] = field(default_factory=dict)
    # Where those shipped figures came from, carried so the interface can say.
    default_note: str = ""
    # When the crew last changed anything, or None if they never have.
    updated_at: float | None = None
    warnings: list[str] = field(default_factory=list)

    def total(self, resource: str) -> float | None:
        return self.totals.get(resource)

    def source(self, resource: str) -> str:
        return self.sources.get(resource, DEFAULT)

    @property
    def is_declared(self) -> bool:
        """Is there a mission to plan against at all?"""
        return self.mission.is_declared

    @property
    def is_all_default(self) -> bool:
        """True while every ceiling on the page is one we shipped."""
        return all(source == DEFAULT for source in self.sources.values())

    def extras_for(self, resource: str) -> list[Extra]:
        """One resource's extras, in the order they are shown: by day, then name."""
        return sorted(
            (extra for extra in self.extras if extra.resource == resource),
            key=lambda extra: (
                extra.kind != DAILY,
                extra.on_date or date.min,
                extra.label.lower(),
            ),
        )

    def suggested_total(self, resource: str) -> float | None:
        """A starting ceiling: the shipped daily figure across the mission."""
        daily = self.suggested_daily.get(resource)
        if daily is None or self.mission.days is None:
            return None
        return round(daily * self.mission.days, 4)


def load_defaults() -> dict[str, Any]:
    """The shipped figures, read from `default_plan.json`.

    Read from a file rather than written into this module so they can be
    replaced for a different habitat without editing code, and so a
    deployment's starting point is a thing you can look at.
    """
    try:
        raw = json.loads(_DEFAULTS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AtlasError(
            f"The shipped mission figures at {_DEFAULTS_FILE.name} could not "
            f"be read: {exc}"
        ) from exc

    from app.habitat import profile

    prof = profile()

    # Suggested per-day figures come from the habitat profile's mission_resources
    # (each resource's default_daily), falling back to default_plan.json's
    # `daily` block for a resource the profile does not give one for.
    file_daily = raw.get("daily", {})
    by_key = {str(r["key"]): r for r in prof.mission_resources if r.get("key")}
    suggested_daily = {
        resource: _optional_number(
            by_key.get(resource, {}).get("default_daily", file_daily.get(resource))
        )
        for resource in RESOURCES
    }

    offset = (
        prof.day_start_offset_minutes
        if prof.day_start_offset_minutes is not None
        else raw.get("day_start_offset_minutes", 0)
    )

    return {
        "suggested_daily": suggested_daily,
        "day_start_offset_minutes": normalise_offset(offset),
        "note": str(raw.get("note", "")),
    }


def _optional_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalise_offset(value: Any) -> int:
    """A day-boundary offset in whole hours, or a refusal saying why."""
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        raise AtlasError(
            f"The day-start offset must be a whole number of minutes, got "
            f"{value!r}."
        ) from None

    if not MIN_OFFSET_MINUTES <= minutes <= MAX_OFFSET_MINUTES:
        raise AtlasError(
            f"The day-start offset must be between {MIN_OFFSET_MINUTES} and "
            f"{MAX_OFFSET_MINUTES} minutes from UTC, got {minutes}."
        )

    if minutes % 60 != 0:
        raise AtlasError(
            "The day-start offset must be a whole number of hours. "
            "Consumption is attributed to hourly buckets, so a boundary "
            "inside an hour would split that hour's use across two days with "
            "no way to say how much belonged to each."
        )

    return minutes


def parse_date(value: Any, what: str = "date") -> date:
    """A calendar date from a request body, or a refusal naming the field."""
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise AtlasError(
            f"The {what} must be a date like '2026-08-01', got {value!r}."
        ) from None


def validate_mission(name: Any, start: Any, days: Any) -> Mission:
    """A mission from a request body, or a refusal saying what is wrong."""
    first = parse_date(start, "mission start date")

    try:
        length = int(days)
    except (TypeError, ValueError):
        raise AtlasError(
            f"The mission length must be a whole number of days, got {days!r}."
        ) from None

    if length < MIN_MISSION_DAYS:
        raise AtlasError(
            f"A mission runs for at least {MIN_MISSION_DAYS} day, got {length}."
        )
    if length > MAX_MISSION_DAYS:
        raise AtlasError(
            f"{length} days is longer than this page lays out day by day (the "
            f"cap is {MAX_MISSION_DAYS}). The plan is a row per day, and past "
            "that it stops being something a crew can read."
        )

    return Mission(
        name=_text(name, MAX_NAME, "mission name"), start=first, days=length
    )


def _text(value: Any, cap: int, what: str) -> str:
    text = "" if value is None else str(value).strip()
    if len(text) > cap:
        raise AtlasError(
            f"The {what} is {len(text)} characters; keep it under {cap} so it "
            "fits where it has to be shown."
        )
    return text


def validate_total(resource: str, value: Any) -> float | None:
    """One resource's mission ceiling, or a refusal naming the field."""
    if resource not in RESOURCES:
        raise AtlasError(
            f"Unknown resource {resource!r}. Use one of: {', '.join(RESOURCES)}."
        )
    return validate_amount(value, f"{RESOURCES[resource].lower()} mission total")


def validate_amount(value: Any, what: str) -> float | None:
    """A quantity, or None where the field was left empty."""
    if value is None:
        return None

    try:
        number = float(value)
    except (TypeError, ValueError):
        raise AtlasError(f"The {what} must be a number, got {value!r}.") from None

    if number != number or number in (float("inf"), float("-inf")):
        raise AtlasError(f"The {what} must be a real number.")
    if number < 0:
        raise AtlasError(
            f"The {what} must not be negative — it is an amount to be "
            "consumed, and a negative one has no meaning. Zero is allowed and "
            "means none is to be drawn at all."
        )
    if number > MAX_TOTAL:
        raise AtlasError(
            f"The {what} of {number:g} is beyond anything this habitat could "
            f"consume (the cap is {MAX_TOTAL:g}). Check the units before "
            "saving it."
        )
    return round(number, 4)


def validate_extra(body: dict[str, Any], mission: Mission) -> dict[str, Any]:
    """One extra from a request body, normalised, or a refusal saying why.

    A one-off is accepted either as a calendar date or as a mission day number,
    because both are how a crew talks: the biology run is "MD-14" in the
    protocol and "the 5th" on the whiteboard.
    """
    resource = str(body.get("resource", "")).strip()
    if resource not in RESOURCES:
        raise AtlasError(
            f"Unknown resource {resource!r}. An extra has to be an extra of "
            f"something: use one of {', '.join(RESOURCES)}."
        )

    label = _text(body.get("label"), MAX_LABEL, "extra's label")
    if not label:
        raise AtlasError(
            "Give the extra a label. A column of numbers with no names on it "
            "is a plan nobody can audit two weeks later."
        )

    amount = validate_amount(body.get("amount"), f"amount for {label!r}")
    if amount is None:
        raise AtlasError(
            f"How much {resource} does {label!r} take? An extra with no amount "
            "moves no day's allowance, so there would be nothing to record."
        )

    kind = str(body.get("kind") or ONCE).strip()
    if kind not in EXTRA_KINDS:
        raise AtlasError(
            f"Unknown recurrence {kind!r}. An extra happens either {ONCE} on a "
            f"given mission day, or {DAILY} for every day of the mission."
        )

    on_date: date | None = None
    if kind == ONCE:
        on_date = _extra_date(body, label, mission)

    return {
        "resource": resource,
        "label": label,
        "amount": amount,
        "kind": kind,
        "on_date": on_date,
        "note": _text(body.get("note"), MAX_NOTE, "extra's note"),
    }


def _extra_date(body: dict[str, Any], label: str, mission: Mission) -> date:
    """Which day a one-off extra lands on, from a date or a mission day number."""
    index = body.get("mission_day")
    if index not in (None, ""):
        try:
            number = int(index)
        except (TypeError, ValueError):
            raise AtlasError(
                f"The mission day for {label!r} must be a number like 14, got "
                f"{index!r}."
            ) from None
        if not mission.is_declared:
            raise AtlasError(
                f"{label!r} was given mission day {number}, but no mission has "
                "been declared yet, so there is no MD-01 to count it from. Set "
                "the mission's start and length first, or give a calendar date."
            )
        assert mission.days is not None
        if not 1 <= number <= mission.days:
            raise AtlasError(
                f"{label!r} is on {day_code(number)}, but this mission runs "
                f"{day_code(1)} to {day_code(mission.days)}."
            )
        found = mission.date_of(number)
        assert found is not None
        return found

    if body.get("on_date") in (None, ""):
        raise AtlasError(
            f"{label!r} happens once, so it needs the day it happens on — that "
            "is the only way to know which day's allowance it comes out of. "
            "Give a mission day or a date, or set it to happen every day."
        )

    when = parse_date(body.get("on_date"), f"date for {label!r}")
    if mission.is_declared and not mission.contains(when):
        end = mission.end
        raise AtlasError(
            f"{label!r} is dated {when.isoformat()}, outside this mission "
            f"({mission.start} to {end}). An extra outside the mission comes "
            "out of no day's allowance, so it would change nothing."
        )
    return when
