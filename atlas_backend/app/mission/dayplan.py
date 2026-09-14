"""The algorithm: a ceiling and a duration in, a day-by-day plan out.

This is the module the mission page exists to run. The crew declares three
things — when the mission starts, how long it runs, and the most of each
resource it may consume end to end — and this turns them into an allowance for
MD-01 through MD-NN, then keeps re-deriving that allowance from what has
actually been drawn.

THE ORIGINAL PLAN, laid down once from the declaration:

    extras_total  = every extra, summed over the days it lands on
    spreadable    = ceiling - extras_total
    flat          = spreadable / mission days
    planned[d]    = flat + extras on d

Extras are carved OUT of the ceiling rather than added to it. A crew that
schedules a 200-litre experiment has not been granted 200 more litres; it has
decided where 200 of its litres go, and every other day drops accordingly. A
ceiling that grew each time someone remembered an experiment would not be one.

By construction sum(planned) == ceiling exactly. That identity is the reason to
compute the plan this way rather than day by day, and it is asserted in the
tests.

THE FORWARD PLAN, re-derived every time the page is read:

    consumed      = what the meters say was drawn on MD-01..today
    left          = ceiling - consumed
    revised[d]    = (left - extras still to come) / days still to come + extras on d

This is the part that makes the page a planning tool rather than a scoreboard.
A crew three days over on water does not want to be told it is over; it wants
to know what a day looks like from here if the mission is still to close on
budget. That number is `revised`, and it moves every time the meters do.

Today counts as a day still to come, because it is: it is running, its
allowance is not yet spent, and dropping it from the divisor would hand the
whole of today's overspend to tomorrow.

WHERE IT STOPS BEING POSSIBLE. If the extras still scheduled cost more than
what is left, no flat rate closes the mission and the plan says so — `feasible`
is false, the shortfall is stated, and the flat part is floored at zero rather
than published as a negative allowance nobody can act on. That state is the
most useful thing this page can ever tell a crew, so it is never rounded away.

NOTHING IS ESTIMATED. A day the sensors did not cover has no actual, and it is
not a day of zero. It is excluded from `consumed` and counted in
`days_uncovered`, so the figure the forward plan works from is stated as the
floor it is — the habitat may have drawn more than we can prove.
"""

from dataclasses import dataclass, field
from datetime import date

from app.mission.plan import CYCLE_DAYS, DAILY, Extra, Mission, day_code

# Verdicts on a day that is over.
OVER = "over"
UNDER = "under"
ON_PLAN = "on_plan"
NO_DATA = "no_data"
# A day not reached yet has no verdict, only an allowance.
PENDING = "pending"

# Where a day sits relative to now.
PAST = "past"
TODAY = "today"
FUTURE = "future"

# How far a day may sit from its allowance and still read as on plan. Meters
# resolve to the litre and the crew does not plan to four decimal places, so a
# day 2% off its figure is a day that went to plan.
TOLERANCE = 0.02


@dataclass
class Day:
    """One mission day: what it was for, what it allowed, what it took."""

    index: int
    code: str
    date: date
    # The UTC instant this local day began — how the meter readings are keyed.
    start: str
    state: str
    # What the original plan allowed: the flat rate plus this day's extras.
    planned: float
    # The extras that land on this day, and what they are.
    extras: float
    extra_labels: list[str] = field(default_factory=list)
    # What the meters say was drawn. None is a day they did not cover.
    actual: float | None = None
    # What the forward plan now allows. Set on today and every day after it;
    # None on a day already behind us, which cannot be re-planned.
    revised: float | None = None
    status: str = PENDING

    @property
    def variance(self) -> float | None:
        """Actual minus planned. Positive is over."""
        if self.actual is None:
            return None
        return round(self.actual - self.planned, 4)


@dataclass
class ResourcePlan:
    """One resource's whole mission, planned and re-planned."""

    resource: str
    # The ceiling the crew declared, or None where they have not.
    total: float | None
    days: list[Day] = field(default_factory=list)

    # -- the original plan ------------------------------------------------
    extras_total: float = 0.0
    flat_per_day: float = 0.0

    # -- where we actually are --------------------------------------------
    consumed: float = 0.0
    days_measured: int = 0
    days_uncovered: int = 0
    days_elapsed: int = 0
    days_remaining: int = 0

    # -- the forward plan --------------------------------------------------
    remaining: float = 0.0
    revised_per_day: float = 0.0
    extras_to_come: float = 0.0
    # False where the extras still scheduled cost more than what is left.
    feasible: bool = True
    shortfall: float = 0.0
    notes: list[str] = field(default_factory=list)

    def day_on(self, when: date) -> Day | None:
        for day in self.days:
            if day.date == when:
                return day
        return None

    def window(self, first: date, last: date) -> list[Day]:
        """Every mission day in `first…last`, both ends included."""
        return [day for day in self.days if first <= day.date <= last]


def build(
    resource: str,
    total: float | None,
    mission: Mission,
    extras: list[Extra],
    used_by_date: dict[date, float],
    today: date,
) -> ResourcePlan:
    """The whole plan for one resource: laid down, measured, and re-derived.

    `used_by_date` is what the meters reported per local day. A date missing
    from it is a day the sensors did not cover, which is not a day of zero.
    """
    out = ResourcePlan(resource=resource, total=total)
    if not mission.is_declared:
        return out

    dates = mission.dates()
    per_day_extras = {
        when: _extras_on(extras, when, mission) for when in dates
    }
    out.extras_total = round(sum(amount for amount, _ in per_day_extras.values()), 4)

    # -- the original plan -------------------------------------------------
    if total is None:
        out.flat_per_day = 0.0
    else:
        spreadable = total - out.extras_total
        out.flat_per_day = round(spreadable / len(dates), 4)
        if spreadable < 0:
            out.notes.append(
                f"The extras booked against this mission come to "
                f"{out.extras_total:g}, more than the whole ceiling of "
                f"{total:g}. Every ordinary day is planned at zero and the "
                "mission cannot close on budget as it stands — raise the "
                "ceiling or drop an extra."
            )
            out.flat_per_day = 0.0

    for index, when in enumerate(dates, start=1):
        amount, labels = per_day_extras[when]
        state = PAST if when < today else (TODAY if when == today else FUTURE)
        out.days.append(
            Day(
                index=index,
                code=day_code(index),
                date=when,
                start="",  # filled by the caller, which owns the offset
                state=state,
                planned=round(out.flat_per_day + amount, 4),
                extras=amount,
                extra_labels=labels,
            )
        )

    # -- where we actually are ---------------------------------------------
    for day in out.days:
        if day.state == FUTURE:
            continue
        out.days_elapsed += 1
        used = used_by_date.get(day.date)
        if used is None:
            out.days_uncovered += 1
            day.status = NO_DATA
            continue
        day.actual = round(used, 4)
        out.consumed = round(out.consumed + used, 4)
        out.days_measured += 1
        day.status = _verdict(used, day.planned, partial=day.state == TODAY)

    out.days_remaining = sum(1 for day in out.days if day.state != PAST)

    # -- the forward plan --------------------------------------------------
    if total is not None:
        out.remaining = round(total - out.consumed, 4)
        out.extras_to_come = round(
            sum(day.extras for day in out.days if day.state != PAST), 4
        )

        if out.days_remaining > 0:
            spreadable = out.remaining - out.extras_to_come
            out.feasible = spreadable >= 0
            if not out.feasible:
                out.shortfall = round(-spreadable, 4)
                spreadable = 0.0
            out.revised_per_day = round(spreadable / out.days_remaining, 4)

            for day in out.days:
                if day.state == PAST:
                    continue
                day.revised = round(out.revised_per_day + day.extras, 4)

    if out.days_uncovered:
        out.notes.append(
            f"{out.days_uncovered} of the {out.days_elapsed} mission days so "
            "far carry no readings. What was drawn on them is unknown and is "
            "not counted as zero, so the consumed figure is a floor and the "
            "allowance ahead is the most optimistic one still consistent with "
            "the record."
        )

    if not out.feasible:
        out.notes.append(
            f"The extras still scheduled come to {out.extras_to_come:g}, more "
            f"than the {out.remaining:g} left in the ceiling — short by "
            f"{out.shortfall:g}. Ordinary days are planned at zero, which is "
            "not a plan: drop or shrink an extra, or raise the ceiling."
        )

    return out


def _extras_on(
    extras: list[Extra], when: date, mission: Mission
) -> tuple[float, list[str]]:
    """What the extras put on one day, and what they are called."""
    amount = 0.0
    labels: list[str] = []
    for extra in extras:
        if not extra.falls_on(when, mission):
            continue
        amount += extra.amount
        labels.append(
            f"{extra.label} ({extra.amount:g})"
            + (" · daily" if extra.kind == DAILY else "")
        )
    return round(amount, 4), labels


def _verdict(used: float, planned: float, partial: bool) -> str:
    """How a day went against its allowance.

    A day still running cannot be under its allowance — it can only not have
    passed it yet — so the only verdict available on today is whether it is
    already over. Calling a morning "under plan" would be the single most
    reassuring wrong thing this page could say.
    """
    if planned <= 0:
        return OVER if used > 0 else ON_PLAN
    ratio = used / planned
    if ratio > 1 + TOLERANCE:
        return OVER
    if partial:
        return ON_PLAN
    if ratio < 1 - TOLERANCE:
        return UNDER
    return ON_PLAN


def cycle_bounds(mission: Mission, today: date) -> tuple[int, int] | None:
    """The mission-day numbers of the three-day cycle containing today.

    Counted from MD-01, so cycle 1 is MD-01…MD-03. Outside the mission there is
    no cycle, and the page says that rather than picking the nearest one.
    """
    index = mission.day_index(today)
    if index is None or not mission.is_declared or not mission.contains(today):
        return None
    assert mission.days is not None
    block = (index - 1) // CYCLE_DAYS
    first = block * CYCLE_DAYS + 1
    last = min(first + CYCLE_DAYS - 1, mission.days)
    return first, last


def cycle_number(mission: Mission, today: date) -> int | None:
    """Which three-day cycle today is in, counting the first as 1."""
    bounds = cycle_bounds(mission, today)
    return None if bounds is None else (bounds[0] - 1) // CYCLE_DAYS + 1
