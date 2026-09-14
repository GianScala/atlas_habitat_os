"""The mission plan, written out for the model.

The crew's plan is the one thing on this system that no sensor knows and no
query returns. Without it ATLAS can say the habitat drew 148 litres today and
cannot say whether that is fine, which is most of what anyone actually wants to
know. So the plan goes into the system prompt on every turn.

WHAT GOES IN THE PROMPT AND WHAT DOES NOT. The plan does — it is small, it
comes from SQLite, and it is the context every answer is read against.
Consumption does NOT: it costs a round trip to the habitat's database, it is
stale the moment it is written, and putting a figure in the system prompt would
hand the model a number it did not query — which is precisely the thing every
other rule in this repository exists to prevent. Live figures arrive the way
every other figure does: through a tool, in the turn that uses them.

So this brief says what was planned and what the day plan implies. It never
says what was used. `get_mission_plan` is the tool that says both, and the
prompt points at it.
"""

from datetime import date

from app.mission import dayplan as dp
from app.mission.plan import DAILY, RESOURCES, Plan, day_code


def mission_brief(plan: Plan, today: date | None = None) -> str:
    """The plan as a prompt section, or a note that there is not one yet."""
    if not plan.is_declared:
        return _UNDECLARED

    mission = plan.mission
    start, end, days = mission.start, mission.end, mission.days
    assert start is not None and end is not None and days is not None

    today = today or date.today()
    index = mission.day_index(today)
    where = (
        f"Today is {day_code(index)} of {day_code(days)}."
        if index is not None and mission.contains(today)
        else (
            f"Today ({today.isoformat()}) is before the mission starts."
            if today < start
            else f"The mission ended on {end.isoformat()}."
        )
    )
    cycle = dp.cycle_number(mission, today)
    if cycle is not None:
        bounds = dp.cycle_bounds(mission, today)
        assert bounds is not None
        where += (
            f" That is inside 3-day cycle {cycle} "
            f"({day_code(bounds[0])}–{day_code(bounds[1])})."
        )

    lines = [
        "",
        "",
        "## The mission plan",
        "",
        "This is what the crew decided before the mission, and what every",
        "consumption question is really asking about. It is a plan, not a",
        "reading: nothing here came from a sensor.",
        "",
        f"Mission: {mission.name or '(unnamed)'}",
        f"Runs {start.isoformat()} to {end.isoformat()} — {days} days, "
        f"MD-01 to {day_code(days)}.",
        where,
        "A mission day begins at 00:00 in the habitat's own clock, not UTC.",
        "",
        "Ceilings — the most that may be drawn across the WHOLE mission:",
    ]

    for key, label in RESOURCES.items():
        total = plan.total(key)
        if total is None:
            lines.append(f"  {label}: no ceiling set.")
            continue
        source = "the crew's figure" if plan.source(key) == "crew" else "a shipped default"
        lines.append(f"  {label}: {total:g} over {days} days ({source}).")

    lines += [
        "",
        "How a day's allowance is worked out: every extra below is carved OUT",
        "of the ceiling and placed on the day it falls on; what is left is",
        "spread evenly over all the mission days. So booking an extra lowers",
        "every other day rather than raising the total. As the mission runs,",
        "whatever is left of the ceiling is re-spread over the days that",
        "remain — that revised figure is what a day should cost from here.",
    ]

    extras = list(plan.extras)
    if extras:
        lines += ["", "Extras the crew has booked:"]
        for extra in extras:
            budgeted = extra.kind == DAILY or mission.contains(extra.on_date or start)
            marker = "" if budgeted else "  [outside the mission — budgeted nowhere]"
            lines.append(f"  - {extra.describe(mission)}{marker}")
            if extra.note:
                lines.append(f"      note: {extra.note}")
    else:
        lines += [
            "",
            "No extras are booked, so every day's allowance is the same flat",
            "figure.",
        ]

    lines += [
        "",
        "You have the plan but NOT the consumption. To say how the crew is",
        "doing against any of this, call get_mission_plan — it returns the",
        "same figures plus what the meters actually recorded, per mission day",
        "and per window. Never estimate progress from this section alone.",
    ]

    return "\n".join(lines)


def crew_log_brief(plan: Plan, logged: dict[str, int]) -> str:
    """Whether the crew's meter log has anything in it, as a prompt section.

    THE SAME RULE AS ABOVE, applied to a second source: what is said here is
    that the log EXISTS and how much of it has been written down. Not one
    consumption figure. A reading count is a fact about the record and moves
    only when somebody types; a litre figure is a measurement, and a
    measurement in the system prompt is a number the model did not query —
    which is the thing every other rule in this repository exists to prevent.

    Kept pure — the counts are passed in — so it can be tested without a
    database and so the caller decides how hard a failure to read them is.
    """
    if not plan.is_declared:
        return ""

    total = sum(logged.values())
    lines = [
        "",
        "",
        "## The crew's meter log",
        "",
        "The habitat is metered twice. Besides the sensors in the database,",
        "the crew walks a round of sub-meter dials and writes the readings",
        "down: seven rooms for power, morning and evening, and eleven taps",
        "for water, once a day. It is the only source that knows which room",
        "or which tap.",
        "",
    ]

    if total == 0:
        lines += [
            "Nothing has been logged yet — the crew has not written down a",
            "single reading. So there is no room-by-room or tap-by-tap figure",
            "to give, and you must not estimate one by dividing a whole-habitat",
            "total between rooms. Say that the log is empty and that it is",
            "filled in on the Dashboard, under Habitat consumption → Crew",
            "meter log.",
        ]
    else:
        counts = ", ".join(
            f"{label} {logged.get(key, 0)}"
            for key, label in (("power", "power"), ("water", "water"))
        )
        lines += [
            f"{total} readings are on record ({counts}). What they add up to",
            "is NOT in this section, on purpose — call get_crew_meter_log for",
            "any figure, and quote what it returns rather than working",
            "anything out from a count.",
        ]

    return "\n".join(lines)


_UNDECLARED = """

## The mission plan

The crew has not declared a mission yet — no start date, no length, no
consumption ceilings. So there is nothing to measure consumption against, and
you must not invent a target, a daily allowance, or a "typical" figure to
compare against.

If someone asks whether consumption is on plan, say plainly that no mission
plan has been set, and that it is set on the Dashboard's Mission view: a start
date, a length in days, and the most of each resource the mission may use. You
can still report what the habitat actually drew, from the telemetry tools, and
you should.
"""
