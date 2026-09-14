"""Used against planned: the answer the mission page exists to give.

The plan comes from `dayplan.py` — an allowance for every mission day, derived
from the ceiling and re-derived from what has actually been drawn. This module
reads the meters, hands them to that algorithm, and rolls the result up into
the three windows a crew asks about: today, this cycle, and the mission.

Every window is a SUM OVER THE SAME DAY PLAN. That is the point. Today's
allowance is a term in this cycle's, which is a term in the mission's, so the
three cards can disagree with each other only if the arithmetic is wrong — not
because someone set three figures that never reconciled.

"We are at 80% of today's water" is two numbers and one trap. The trap is that
80% is not a verdict on its own — at breakfast it is alarming and at midnight
it is a good day. So every window carries three figures, not one:

    used_fraction    how much of the allowance is gone.
    elapsed          how much of the window is gone.
    pace_ratio       the first divided by the second — above 1 the crew is
                     spending faster than the window is passing.

And one more the old page could not produce, because it had no day plan:

    planned_by_now   what the plan itself expected by this moment. Not the
                     allowance times the elapsed fraction — a 200-litre
                     experiment booked for the last day of a cycle is not
                     two-thirds spent on the second day, and pacing against it
                     as though it were would report a crew comfortably ahead
                     right up until it wasn't.

A status is assigned from the pace, not from the fraction, and it is one of
three so it can be one of the three instrument colours: nominal, caution, over.

EARLY IN A WINDOW THERE IS NO PACE. Four minutes into a day, a single draw
extrapolates to a fortnight of water. Below `periods.PACE_FLOOR` of the window
elapsed, no projection is published and the status falls back to the only thing
still true — whether the allowance has been spent.

NOTHING IS ESTIMATED. A day the sensors did not cover is reported as uncovered,
with the count attached, and its total is the sum of the days that did report —
never scaled up to pretend the rest was measured.
"""

from datetime import UTC, datetime
from functools import partial
from typing import Any

from app.core.concurrency import gather
from app.mission import dayplan as dp
from app.mission import meters as mt
from app.mission import periods as per
from app.mission.plan import HORIZONS, Plan

# The furthest back the meters are asked to go, in local days. A mission longer
# than this still lays out every day; the days beyond the cap simply carry no
# measured figure and say so, which is the same treatment a day with no sensor
# coverage already gets. The cap sits inside the 90-period ceiling the telemetry
# helpers trim their breakdowns at, so a request can never silently lose its
# oldest days.
MAX_LOOKBACK_DAYS = 90

NOMINAL = "nominal"
CAUTION = "caution"
OVER = "over"
UNSET = "unset"
NO_DATA = "no_data"

# Where the mission sits relative to now.
BEFORE = "before"
RUNNING = "running"
AFTER = "after"


def build_tracking(plan: Plan) -> dict[str, Any]:
    """The whole mission page: the calendar, every window, and the forward plan."""
    offset = plan.day_start_offset_minutes
    now = datetime.now(UTC)
    today = per.local_date(now, offset)
    mission = plan.mission

    envelope: dict[str, Any] = {
        "generated_at": per.iso(now),
        "day_start_offset_minutes": offset,
        "day_start_label": f"00:00 {per.offset_label(offset)}",
        "mission": _mission_block(plan, today, now),
        "plan_updated_at": plan.updated_at,
        "plan_is_all_default": plan.is_all_default,
        "default_note": plan.default_note,
        "warnings": list(plan.warnings),
        "resources": [],
    }

    if not mission.is_declared:
        # Nothing to measure against, so nothing is measured. The page shows
        # the setup instead, and a habitat with no plan does not spend a
        # database round trip finding that out.
        envelope["resources"] = [_undeclared(meter) for meter in mt.METERS]
        return envelope

    live = per.current_periods(now, offset, mission)
    day_elapsed = per.day_elapsed_fraction(now, offset)

    start, end = mission.start, mission.end
    assert start is not None and end is not None
    # Only the part of the mission that has happened is worth querying, and
    # only as far back as the cap allows.
    query_from = per.start_of_local_day(
        per.clamp_to_history(start, today, MAX_LOOKBACK_DAYS), offset
    )

    # Each resource is its own query and they share only the window, so they
    # are read together. Sequentially, the page waited for water before it
    # started asking about power.
    envelope["resources"] = gather(
        [
            partial(_resource, meter, plan, query_from, today, day_elapsed, live, now)
            for meter in mt.METERS
        ]
    )
    return envelope


def _mission_block(plan: Plan, today, now: datetime) -> dict[str, Any]:
    """The mission itself: where it runs, and where in it we are."""
    mission = plan.mission
    if not mission.is_declared:
        return {
            "is_declared": False,
            "name": mission.name,
            "start": None,
            "end": None,
            "days": None,
            "state": BEFORE,
            "day_index": None,
            "day_code": None,
            "days_elapsed": 0,
            "days_remaining": None,
            "elapsed_fraction": 0.0,
            "cycle_number": None,
            "cycle_first": None,
            "cycle_last": None,
            "today": today.isoformat(),
        }

    start, end, days = mission.start, mission.end, mission.days
    assert start is not None and end is not None and days is not None

    index = mission.day_index(today)
    assert index is not None
    inside = mission.contains(today)
    state = RUNNING if inside else (BEFORE if today < start else AFTER)

    window = per.current_periods(now, plan.day_start_offset_minutes, mission).get(
        "mission"
    )
    bounds = dp.cycle_bounds(mission, today)

    return {
        "is_declared": True,
        "name": mission.name,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days": days,
        "state": state,
        "day_index": index if inside else None,
        "day_code": dp.day_code(index) if inside else None,
        # Days behind us, capped at the mission's own length: a page read a
        # week after splashdown says the mission is over, not that it is on
        # day thirty-seven of thirty.
        "days_elapsed": max(0, min(days, index - 1 if not inside else index)),
        "days_remaining": max(0, (end - today).days + 1) if today <= end else 0,
        "elapsed_fraction": round(window.elapsed_fraction if window else 1.0, 4),
        "cycle_number": dp.cycle_number(mission, today),
        "cycle_first": bounds[0] if bounds else None,
        "cycle_last": bounds[1] if bounds else None,
        "today": today.isoformat(),
    }


def _undeclared(meter: mt.Meter) -> dict[str, Any]:
    """A resource on a page with no mission: named, and nothing else."""
    return {
        "key": meter.key,
        "label": meter.label,
        "noun": meter.noun,
        "unit": "",
        "unit_source": "unknown",
        "measurement": meter.measurement,
        "field": meter.field,
        "query": "",
        "total": None,
        "source": "default",
        "flat_per_day": None,
        "revised_per_day": None,
        "extras_total": 0.0,
        "extras_to_come": 0.0,
        "consumed": None,
        "remaining": None,
        "feasible": True,
        "shortfall": 0.0,
        "days_measured": 0,
        "days_uncovered": 0,
        "budgets": [],
        "days": [],
        "extras": [],
        "notes": [],
        "error": None,
    }


def _resource(
    meter: mt.Meter,
    plan: Plan,
    query_from: datetime,
    today,
    day_elapsed: float,
    live: dict[str, per.Period],
    now: datetime,
) -> dict[str, Any]:
    """One resource: its day plan, its windows, and where its numbers came from."""
    offset = plan.day_start_offset_minutes
    use = mt.daily_use(meter, query_from, offset)

    computed = dp.build(
        resource=meter.key,
        total=plan.total(meter.key),
        mission=plan.mission,
        extras=plan.extras_for(meter.key),
        used_by_date={} if use.error else use.per_date,
        today=today,
    )

    days = [
        {
            "index": day.index,
            "code": day.code,
            "date": day.date.isoformat(),
            "start": per.iso(per.start_of_local_day(day.date, offset)),
            "state": day.state,
            "planned": day.planned,
            "revised": day.revised,
            "extras": day.extras,
            "extra_labels": list(day.extra_labels),
            "actual": day.actual,
            "variance": day.variance,
            "status": day.status,
            # A day older than the query window was never asked about. It is
            # reported as unmeasured rather than as a gap in the sensors,
            # because the two have different fixes.
            "queried": day.date >= per.local_date(query_from, offset),
        }
        for day in computed.days
    ]

    budgets = [
        _budget(live[horizon], computed, plan, meter.key, day_elapsed)
        for horizon in HORIZONS
        if horizon in live
    ]

    return {
        "key": meter.key,
        "label": meter.label,
        "noun": meter.noun,
        "unit": use.unit,
        "unit_source": use.unit_source,
        "measurement": meter.measurement,
        "field": meter.field,
        "query": use.query,
        "total": computed.total,
        "source": plan.source(meter.key),
        "flat_per_day": computed.flat_per_day if computed.total is not None else None,
        "revised_per_day": (
            computed.revised_per_day if computed.total is not None else None
        ),
        "extras_total": computed.extras_total,
        "extras_to_come": computed.extras_to_come,
        "consumed": computed.consumed if computed.days_measured else None,
        "remaining": computed.remaining if computed.total is not None else None,
        "feasible": computed.feasible,
        "shortfall": computed.shortfall,
        "days_measured": computed.days_measured,
        "days_uncovered": computed.days_uncovered,
        "budgets": budgets,
        "days": days,
        "extras": [_extra(extra, plan) for extra in plan.extras_for(meter.key)],
        "notes": list(use.notes) + list(computed.notes),
        "error": use.error,
    }


def _extra(extra, plan: Plan) -> dict[str, Any]:
    index = (
        plan.mission.day_index(extra.on_date) if extra.on_date is not None else None
    )
    inside = extra.on_date is not None and plan.mission.contains(extra.on_date)
    return {
        "id": extra.id,
        "resource": extra.resource,
        "label": extra.label,
        "amount": extra.amount,
        "kind": extra.kind,
        "on_date": None if extra.on_date is None else extra.on_date.isoformat(),
        "mission_day": index if inside else None,
        "day_code": dp.day_code(index) if inside and index is not None else None,
        "note": extra.note,
        # True where the crew has moved the mission out from under it.
        "stranded": extra.on_date is not None and not inside,
        "updated_at": extra.updated_at,
    }


def _budget(
    period: per.Period,
    computed: dp.ResourcePlan,
    plan: Plan,
    resource: str,
    day_elapsed: float,
) -> dict[str, Any]:
    """One resource against one window of the day plan."""
    days = computed.window(period.first_date, period.last_date)
    measured = [day.actual for day in days if day.actual is not None]
    covered = len(measured)
    # A day still ahead of us is not a day the sensors missed.
    expected = sum(1 for day in days if day.state != dp.FUTURE)
    used: float | None = round(sum(measured), 4) if measured else None

    # No ceiling means no allowance. The day plan still lays the window out —
    # every day at zero — and summing that would report a window budgeted at
    # nothing, which reads as "draw none of this" and is the opposite of
    # "nobody has capped it".
    target = (
        round(sum(day.planned for day in days), 4)
        if days and computed.total is not None
        else None
    )
    revised = [day.revised for day in days if day.revised is not None]
    elapsed = period.elapsed_fraction

    out: dict[str, Any] = {
        "horizon": period.horizon,
        "label": period.label,
        "days": period.days,
        "period_start": per.iso(period.start),
        "period_end": per.iso(period.end),
        "first_code": days[0].code if days else None,
        "last_code": days[-1].code if days else None,
        "elapsed_fraction": round(elapsed, 4),
        "used": used,
        "target": target,
        # What the forward plan now allows across this window's remaining days,
        # on top of what its finished days already took.
        "revised_target": (
            round(sum(day.planned for day in days if day.state == dp.PAST) + sum(revised), 4)
            if revised
            else None
        ),
        "extras": round(sum(day.extras for day in days), 4),
        "source": plan.source(resource),
        "days_covered": covered,
        "days_expected": expected,
        "used_fraction": None,
        "planned_by_now": _planned_by_now(days, day_elapsed),
        "remaining": None,
        "projected": None,
        "pace_ratio": None,
        "status": NOMINAL,
        "note": None,
    }

    if used is None:
        out["status"] = NO_DATA
        out["note"] = (
            "No readings covered this window, so nothing can be said about it."
        )
        return out

    if covered < expected:
        missing = expected - covered
        out["note"] = (
            f"{missing} of the {expected} days elapsed in this window carry no "
            "readings. The figure is the sum of the days that do, and is a "
            "floor rather than the whole window's use."
        )

    if target is None:
        out["status"] = UNSET
        return out

    out["remaining"] = round(target - used, 4)

    if target == 0:
        # A zero allowance is a real plan — "draw none of this" — and any draw
        # at all breaks it. Dividing by it would not.
        out["status"] = OVER if used > 0 else NOMINAL
        out["note"] = out["note"] or (
            "This window is planned at zero: none of this resource is to be "
            "drawn at all."
        )
        return out

    out["used_fraction"] = round(used / target, 4)

    if used > target:
        out["status"] = OVER
        return out

    if not period.pace_is_readable:
        out["status"] = NOMINAL
        out["note"] = out["note"] or (
            f"Only {elapsed * 100:.0f}% of this window has passed. A rate read "
            "from it would extrapolate a few minutes across the whole window, "
            "so no projection is given yet."
        )
        return out

    out["projected"] = round(used / elapsed, 4)
    out["pace_ratio"] = round((used / target) / elapsed, 4)

    # Judged against what the plan expected by now, not against the elapsed
    # share of the allowance — those differ by exactly the extras, which is the
    # whole reason the crew entered them.
    ahead = out["planned_by_now"]
    if ahead is not None and ahead > 0:
        out["pace_ratio"] = round(used / ahead, 4)

    out["status"] = CAUTION if out["projected"] > target else NOMINAL
    return out


def _planned_by_now(days: list[dp.Day], day_elapsed: float) -> float | None:
    """What the plan expected to have been drawn by this moment.

    Finished days in full, today at the share of it that has passed, days still
    ahead at nothing. Extras land on their own day rather than being smeared
    across the window, which is the difference between this figure and the
    allowance times the elapsed fraction.
    """
    if not days:
        return None
    total = 0.0
    for day in days:
        if day.state == dp.PAST:
            total += day.planned
        elif day.state == dp.TODAY:
            total += day.planned * day_elapsed
    return round(total, 4)
