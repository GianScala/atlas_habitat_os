"""When today, this cycle, and the mission begin — in the habitat's own clock.

Three windows, all anchored to the mission:

  day      local midnight. The one everybody means by "today".
  cycle    the three-day block of mission days containing today, counted from
           MD-01. Three days is not a calendar unit, so it needs a starting
           point; the mission's own first day is the only honest one.
  mission  MD-01 to the last day, inclusive.

All three are half-open: a period includes its start and excludes its end, so
the instant one closes is the instant the next opens and no reading is filed
under two of them.

Everything here returns UTC instants. The offset is applied to decide WHICH
instant a local boundary falls on, never to relabel one.

None of the three exists before the crew declares a mission, and this module
returns nothing rather than inventing one. A cycle counted from an arbitrary
date would look exactly like a cycle counted from MD-01 and be wrong.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from app.mission import dayplan
from app.mission.plan import HORIZONS, Mission

# Below this much of a period elapsed, a projection from the current rate is
# arithmetic rather than information: four minutes into a day, one flush of
# the tank extrapolates to a fortnight's water. Under it, pace is reported as
# unavailable rather than as a very large number.
PACE_FLOOR = 0.1


@dataclass(frozen=True)
class Period:
    """One horizon's current window, and how far into it we are."""

    horizon: str
    label: str
    days: int
    start: datetime
    end: datetime
    now: datetime
    # The local dates the window covers, both ends included. Carried because
    # everything downstream sums the day plan over exactly these.
    first_date: date
    last_date: date

    @property
    def elapsed_fraction(self) -> float:
        """How much of this period is behind us, clamped to 0…1."""
        span = (self.end - self.start).total_seconds()
        if span <= 0:
            return 1.0
        lived = (self.now - self.start).total_seconds()
        return max(0.0, min(1.0, lived / span))

    @property
    def pace_is_readable(self) -> bool:
        """Has enough of the period passed for its rate to mean anything?"""
        return self.elapsed_fraction >= PACE_FLOOR


def local_date(moment: datetime, offset_minutes: int) -> date:
    """The habitat's calendar date at a UTC instant."""
    return (moment.astimezone(UTC) + timedelta(minutes=offset_minutes)).date()


def start_of_local_day(day: date, offset_minutes: int) -> datetime:
    """The UTC instant a given local date began."""
    midnight = datetime(day.year, day.month, day.day, tzinfo=UTC)
    return midnight - timedelta(minutes=offset_minutes)


def day_elapsed_fraction(now: datetime, offset_minutes: int) -> float:
    """How much of the current local day has passed, 0…1.

    The share an extra scheduled for today is counted at: a task planned for
    this afternoon has not happened yet at breakfast.
    """
    today = local_date(now, offset_minutes)
    start = start_of_local_day(today, offset_minutes)
    lived = (now.astimezone(UTC) - start).total_seconds()
    return max(0.0, min(1.0, lived / 86400.0))


def current_periods(
    now: datetime, offset_minutes: int, mission: Mission
) -> dict[str, Period]:
    """The live window for every horizon, keyed by horizon.

    Empty while no mission is declared, and missing the cycle and the mission
    on a day outside one — a crew reading the page a week before launch is
    shown the setup, not a cycle invented to fill the space.
    """
    now = now.astimezone(UTC)
    today = local_date(now, offset_minutes)
    periods: dict[str, Period] = {}

    def add(horizon: str, first: date, last: date) -> None:
        start = start_of_local_day(first, offset_minutes)
        end = start_of_local_day(last + timedelta(days=1), offset_minutes)
        periods[horizon] = Period(
            horizon=horizon,
            label=HORIZONS[horizon].label,
            days=(last - first).days + 1,
            start=start,
            end=end,
            now=now,
            first_date=first,
            last_date=last,
        )

    add("day", today, today)

    if not mission.is_declared:
        return periods

    bounds = dayplan.cycle_bounds(mission, today)
    if bounds is not None:
        first = mission.date_of(bounds[0])
        last = mission.date_of(bounds[1])
        assert first is not None and last is not None
        add("cycle", first, last)

    start, end = mission.start, mission.end
    assert start is not None and end is not None
    add("mission", start, end)

    return periods


def local_days(first: date, last: date, offset_minutes: int) -> list[datetime]:
    """Every local day start from `first` to `last` inclusive, as UTC instants.

    Built by walking dates rather than by adding 24 hours repeatedly: the two
    agree only while the offset holds still, and walking dates is the one that
    keeps meaning what it says if it ever does not.
    """
    out: list[datetime] = []
    day = first
    while day <= last:
        out.append(start_of_local_day(day, offset_minutes))
        day += timedelta(days=1)
    return out


def offset_label(offset_minutes: int) -> str:
    """`UTC+02:00` — how the day boundary is described on screen."""
    sign = "+" if offset_minutes >= 0 else "-"
    hours, minutes = divmod(abs(offset_minutes), 60)
    return f"UTC{sign}{hours:02d}:{minutes:02d}"


def iso(moment: datetime) -> str:
    """A UTC instant in the same spelling the telemetry layer uses."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def clamp_to_history(first: date, today: date, cap: int) -> date:
    """The earliest date worth querying: `first`, or `cap` days back.

    A hundred-day mission read on day ninety would otherwise ask the database
    for ninety days of hourly buckets on every page load. The plan still lays
    out every day; the days beyond the cap simply have no measured figure, and
    say so, which is the same treatment a day with no sensor coverage gets.
    """
    floor = today - timedelta(days=cap - 1)
    return max(first, floor)


def optional_local_date(value: datetime | None, offset_minutes: int) -> date | None:
    return None if value is None else local_date(value, offset_minutes)
