"""Which instrument answers "how much did we use", and how to read it per day.

Two resources, two completely different kinds of number, and the difference is
not a detail:

  WATER is a stock in a tank. The gauge goes down when the crew drinks and up
  when a delivery arrives, and netting the two describes neither. So water is
  read through `tanks.get_tank_flow`, which reports the fall and the rise
  separately; consumption is the fall.

  POWER is a cumulative totaliser that only climbs. Consumption is the
  distance it climbed, and it is read through `aggregation.get_consumption`,
  which verifies that it really did only climb before calling any of it use.

Both are the same helpers the chat tools call, on purpose. A crew that asks
ATLAS "how much water did we use today" and then looks at the mission page
must not be given two different answers, and the only way to guarantee that is
for both to be the same query.

ONE QUERY PER RESOURCE, covering everything the page needs. The alternative —
a query per horizon — would let the day, the cycle, and the week disagree
about the same afternoon, since each would apply the water deadband over a
different window. Reading local days once and adding them up means today's
figure is a term in this week's by construction.

THE LEAD-IN. The energy figure for a day is where the meter stood at the end
of it minus where it stood at the end of the day before, so the first day
reported needs a day before it to be measured against. That day is fetched and
discarded, never estimated. Taking each day's own first and last reading
instead would have been simpler and would have dropped the minute between one
day's last reading and the next day's first — invisibly, and always downwards.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from app.core.errors import AtlasError
from app.core.logging import get_logger
from app.mission import periods as per
from app.telemetry.aggregation import get_consumption
from app.telemetry.tanks import get_tank_flow

log = get_logger(__name__)


@dataclass(frozen=True)
class Meter:
    """One resource, and the gauge that says how much of it went."""

    key: str
    label: str
    # What the number is, in words, for the card's caption.
    noun: str
    measurement: str
    field: str
    tags: dict[str, str]
    # How the gauge is read: a STOCK (a tank level, differenced by get_tank_flow)
    # or a CUMULATIVE meter (a totaliser, differenced by get_consumption).
    kind: str = "cumulative"


def _meters_from_profile() -> tuple[Meter, ...]:
    """The mission meters this habitat declares, from its profile.

    The telemetry that reads each budgeted resource is habitat-specific, so it
    lives in the profile's `mission_resources:` section rather than here. A
    habitat that declares none simply has no meters, and the mission plan tracks
    nothing against telemetry (it still holds the crew's declared plan).
    """
    from app.habitat import profile

    meters: list[Meter] = []
    for r in profile().mission_resources:
        if not r.get("key"):
            continue
        meters.append(
            Meter(
                key=str(r["key"]),
                label=str(r.get("label", r["key"])),
                noun=str(r.get("noun", "")),
                measurement=str(r.get("measurement", "")),
                field=str(r.get("field", "")),
                tags=dict(r.get("tags") or {}),
                kind=str(r.get("kind", "cumulative")),
            )
        )
    return tuple(meters)


# Resolved once at import, like the rest of the habitat profile.
METERS: tuple[Meter, ...] = _meters_from_profile()

METERS_BY_KEY = {meter.key: meter for meter in METERS}


@dataclass
class DailyUse:
    """What one meter says was used on each local day of a window.

    Keyed by the habitat's own calendar date, not by a UTC instant, because
    every consumer of this — the day plan, the cards, the calendar — thinks in
    local days, and converting in one place beats converting in six.

    A date absent from `per_date` is a day the sensors did not cover. It is not
    a day of zero use, and nothing here fills it in.
    """

    per_date: dict[date, float] = field(default_factory=dict)
    unit: str = ""
    unit_source: str = "unknown"
    query: str = ""
    notes: list[str] = field(default_factory=list)
    error: str | None = None

    def total(self, days: list[date]) -> tuple[float | None, int]:
        """(sum over those local days, how many of them had no readings)."""
        found = [self.per_date[day] for day in days if day in self.per_date]
        missing = len(days) - len(found)
        if not found:
            return None, missing
        return round(sum(found), 4), missing


def daily_use(meter: Meter, start: datetime, offset_minutes: int) -> DailyUse:
    """Per-local-day consumption from `start` until now, for one meter.

    A failure here is confined to its own resource: a broken water gauge
    should not take the power budget off the page with it. A resource whose
    gauge this habitat does not record is reported as untracked rather than as
    an error, so a mission can budget something its sensors do not yet cover.
    """
    missing = _unavailable(meter)
    if missing:
        return DailyUse(error=missing)
    try:
        if meter.kind == "stock":
            return _water_by_day(meter, start, offset_minutes)
        return _energy_by_day(meter, start, offset_minutes)
    except AtlasError as exc:
        log.warning("Mission meter %s failed: %s", meter.key, exc.message)
        return DailyUse(error=exc.message)


def _unavailable(meter: Meter) -> str | None:
    """A reason string if this meter's gauge isn't in the database, else None."""
    from app.telemetry import discovery

    if not meter.measurement or not meter.field:
        return "No gauge is configured for this resource."
    try:
        if meter.measurement not in discovery.discover()["habitat"]:
            return f"{meter.measurement} is not recorded in this habitat."
        fields = {f["field"] for f in discovery.field_keys(meter.measurement)}
    except AtlasError:
        return None  # can't reach the schema — let the real query report it
    if meter.field not in fields:
        return f"{meter.measurement} has no field {meter.field!r} in this habitat."
    return None


def _water_by_day(meter: Meter, start: datetime, offset_minutes: int) -> DailyUse:
    """The fall of the supply tank, per local day.

    Exactly one gauge has to match. Two gauges on one tank are two opinions
    about the same water: adding them doubles it and picking one silently
    discards the other, so neither is done — the resource reports that the
    filter is too loose and says which tag values it found.
    """
    result = get_tank_flow(
        meter.measurement,
        meter.field,
        tags=dict(meter.tags),
        start=per.iso(start),
        group_by="day",
        offset_minutes=offset_minutes,
    )
    out = DailyUse(
        unit=result.get("unit", ""),
        unit_source=result.get("unit_source", "unknown"),
        query=result.get("query", ""),
    )

    series = (result.get("data") or {}).get("series") or []
    if not series:
        out.error = (
            f"No readings from {meter.measurement}.{meter.field} for "
            f"{_describe_tags(meter.tags)} since {per.iso(start)}."
        )
        return out

    if len(series) > 1:
        out.error = (
            f"{len(series)} separate gauges match {_describe_tags(meter.tags)} "
            f"({_describe_series(series)}). Two gauges on one tank are two "
            "opinions about the same water — adding them would double it and "
            "choosing one would discard the other, so no consumption figure "
            "was computed. Narrow the filter to a single gauge."
        )
        return out

    entry = series[0]
    for period in entry.get("per_period", []):
        when = _local_date(str(period["period_start"]), offset_minutes)
        out.per_date[when] = float(period["fell"])

    if result.get("deadband"):
        out.notes.append(
            f"Movements under {result['deadband']:g} {out.unit or 'units'} are "
            "below what this gauge can resolve and are read as no use, so a "
            "period only just under way can read low until the first real draw "
            "clears the threshold."
        )
    if result.get("deadband_warning"):
        out.notes.append(result["deadband_warning"])

    return out


def _energy_by_day(meter: Meter, start: datetime, offset_minutes: int) -> DailyUse:
    """How far the habitat's totaliser climbed on each local day.

    A day's figure is the meter at the end of it minus the meter at the end of
    the day before, so a day whose predecessor is missing has no figure rather
    than a figure covering two days. Reporting one would have put a quiet day
    and its neighbour's use on the same bar.
    """
    lead = start - timedelta(days=1)
    result = get_consumption(
        meter.measurement,
        meter.field,
        tags=dict(meter.tags),
        start=per.iso(lead),
        group_by="day",
        offset_minutes=offset_minutes,
    )
    out = DailyUse(
        unit=result.get("unit", ""),
        unit_source=result.get("unit_source", "unknown"),
        query=result.get("query", ""),
    )

    series = (result.get("data") or {}).get("series") or []
    if not series:
        out.error = (
            f"No readings from {meter.measurement}.{meter.field} for "
            f"{_describe_tags(meter.tags)} since {per.iso(lead)}."
        )
        return out

    if not result.get("cumulative", False):
        out.error = (
            result.get("warning")
            or f"{meter.measurement}.{meter.field} decreased during this "
            "window, so it is not behaving as a totaliser and none of its "
            "movement can be called consumption."
        )
        return out

    # Every matching meter is climbed separately and the climbs are added.
    # Energy from two meters is energy; this is the one place where summing
    # across series is the right thing to do, and `get_consumption` verified
    # each one on its own before we got here.
    for entry in series:
        climbs = _climb_per_day(entry.get("per_period", []), offset_minutes)
        for day, amount in climbs.items():
            out.per_date[day] = round(out.per_date.get(day, 0.0) + amount, 4)

    if len(series) > 1:
        out.notes.append(
            f"{len(series)} meters match {_describe_tags(meter.tags)}; each was "
            "differenced on its own and the results added."
        )

    return out


def _climb_per_day(
    rows: list[dict[str, Any]], offset_minutes: int
) -> dict[date, float]:
    """Day-end to day-end differences, keyed by the day they belong to.

    The first row is the lead-in and is consumed rather than reported, and a
    row whose predecessor is not the day before it is skipped — its climb
    spans a gap in the record and belongs to no single day.
    """
    ordered = sorted(
        (row for row in rows if row.get("last") is not None),
        key=lambda row: str(row["period_start"]),
    )

    out: dict[date, float] = {}
    for previous, current in zip(ordered, ordered[1:], strict=False):
        gap = _days_between(str(previous["period_start"]), str(current["period_start"]))
        if gap != 1:
            continue
        climb = float(current["last"]) - float(previous["last"])
        # A totaliser cannot go backwards, and get_consumption already refused
        # the window if one did. A residual negative here would be a rounding
        # artefact, not a reading, so it contributes nothing.
        when = _local_date(str(current["period_start"]), offset_minutes)
        out[when] = round(max(0.0, climb), 4)

    return out


def _local_date(instant: str, offset_minutes: int) -> date:
    """The habitat's calendar date a bucket belongs to.

    The buckets were already cut on local midnights by the offset passed to the
    query, so this is a relabelling of an instant we chose, not a second guess
    at which day a reading fell in.
    """
    return per.local_date(_parse(instant), offset_minutes)


def _parse(instant: str) -> datetime:
    return datetime.fromisoformat(instant.replace("Z", "+00:00"))


def _days_between(first: str, second: str) -> int:
    return round((_parse(second) - _parse(first)).total_seconds() / 86400)


def _describe_tags(tags: dict[str, str]) -> str:
    return ", ".join(f"{key}={value}" for key, value in tags.items()) or "no filter"


def _describe_series(series: list[dict[str, Any]]) -> str:
    return "; ".join(
        ", ".join(f"{k}={v}" for k, v in entry.get("tags", {}).items())
        for entry in series
    )
