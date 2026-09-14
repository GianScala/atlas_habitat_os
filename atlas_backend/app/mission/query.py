"""The mission plan as a tool result: planned, drawn, and what is left.

The same `build_tracking` the mission page draws, flattened into something a
model can read in one pass and quote from without arithmetic. The page and the
tool are the same computation on purpose: a crew that asks ATLAS "are we on
plan for water" and then opens the mission view must not be given two different
answers, and the only way to guarantee that is for both to be one function.

WHAT IS TRIMMED. Four hundred mission days of per-day rows would crowd out
everything else in the context and be read by nobody. So the day-by-day
breakdown is windowed — the days around today, plus every day carrying an
extra, which are the ones that explain a lumpy allowance. The full calendar is
on the page; a model that needs a specific day can ask for it.
"""

from typing import Any

from app.mission import repository as repo
from app.mission import tracking as track
from app.mission.plan import day_code

# Days of the calendar returned around today. Enough to see the run-in and the
# run-out of the current cycle without burying the summary.
DAYS_BEFORE = 7
DAYS_AFTER = 7
MAX_DAYS = 40


def get_mission_plan(resource: str | None = None) -> dict[str, Any]:
    """The mission plan and consumption against it.

    Args:
        resource: limit to one resource ("water" or "power"). Omit for both.
    """
    plan = repo.load_plan()
    built = track.build_tracking(plan)
    mission = built["mission"]

    if not mission["is_declared"]:
        return {
            "mission_declared": False,
            "note": (
                "No mission has been declared: no start date, no length, and no "
                "consumption ceilings. There is nothing to measure consumption "
                "against. Say so rather than comparing against a figure you "
                "invented. The crew sets it on the Dashboard's Mission view."
            ),
            "resources": [],
        }

    wanted = (resource or "").strip().lower()
    resources = [
        row
        for row in built["resources"]
        if not wanted or row["key"] == wanted
    ]
    if wanted and not resources:
        available = ", ".join(row["key"] for row in built["resources"])
        raise ValueError(
            f"No mission resource called {wanted!r}. Available: {available}."
        )

    return {
        "mission_declared": True,
        "generated_at": built["generated_at"],
        "day_boundary": built["day_start_label"],
        "mission": {
            "name": mission["name"],
            "start": mission["start"],
            "end": mission["end"],
            "days": mission["days"],
            "state": mission["state"],
            "today": mission["today"],
            "today_is": mission["day_code"],
            "days_elapsed": mission["days_elapsed"],
            "days_remaining": mission["days_remaining"],
            "cycle": _cycle(mission),
        },
        "plan_is_shipped_default": built["plan_is_all_default"],
        "warnings": built["warnings"],
        "resources": [_resource(row) for row in resources],
        "reading_notes": [
            "Every figure under 'planned' is the crew's plan. Every figure "
            "under 'actual' or 'used' came from the meters named in 'source'.",
            "'revised_per_day' is what an ordinary day may cost FROM NOW ON if "
            "the mission is still to close inside its ceiling. It is the "
            "number to quote when asked what the crew should be doing.",
            "A day with actual: null is a day the sensors did not cover. It is "
            "not a day of zero use, and it must not be summed as one.",
        ],
    }


def _cycle(mission: dict[str, Any]) -> dict[str, Any] | None:
    if mission["cycle_number"] is None:
        return None
    return {
        "number": mission["cycle_number"],
        "first": day_code(mission["cycle_first"]),
        "last": day_code(mission["cycle_last"]),
    }


def _resource(row: dict[str, Any]) -> dict[str, Any]:
    unit = row["unit"] if row["unit_source"] == "known" else None

    return {
        "resource": row["key"],
        "label": row["label"],
        "unit": unit,
        "unit_source": row["unit_source"],
        "source": {
            "measurement": row["measurement"],
            "field": row["field"],
            "read_as": row["noun"],
            "query": row["query"],
        },
        "error": row["error"],
        "plan": {
            "mission_ceiling": row["total"],
            "ceiling_is": "the crew's figure"
            if row["source"] == "crew"
            else "a shipped default the crew has not replaced",
            "flat_per_day": row["flat_per_day"],
            "extras_total": row["extras_total"],
        },
        "position": {
            "consumed_so_far": row["consumed"],
            "remaining_in_ceiling": row["remaining"],
            "days_measured": row["days_measured"],
            "days_without_readings": row["days_uncovered"],
        },
        "forward_plan": {
            "revised_per_day": row["revised_per_day"],
            "extras_still_to_come": row["extras_to_come"],
            "closes_on_budget": row["feasible"],
            "shortfall": row["shortfall"] or None,
        },
        "windows": [_window(budget) for budget in row["budgets"]],
        "extras": [
            {
                "label": extra["label"],
                "amount": extra["amount"],
                "when": "every day" if extra["kind"] == "daily" else extra["day_code"],
                "date": extra["on_date"],
                "note": extra["note"] or None,
                "outside_the_mission": extra["stranded"],
            }
            for extra in row["extras"]
        ],
        "days": _days(row["days"]),
        "notes": row["notes"],
    }


def _window(budget: dict[str, Any]) -> dict[str, Any]:
    return {
        "window": budget["label"],
        "horizon": budget["horizon"],
        "covers": _covers(budget),
        "planned": budget["target"],
        "planned_by_now": budget["planned_by_now"],
        "used": budget["used"],
        "used_fraction_of_plan": budget["used_fraction"],
        "remaining": budget["remaining"],
        "window_elapsed_fraction": budget["elapsed_fraction"],
        "pace_ratio": budget["pace_ratio"],
        "pace_means": (
            "used divided by what the plan expected by now — above 1 is "
            "spending faster than planned"
        ),
        "projected_end_of_window": budget["projected"],
        "status": budget["status"],
        "days_with_readings": budget["days_covered"],
        "days_elapsed_in_window": budget["days_expected"],
        "note": budget["note"],
    }


def _covers(budget: dict[str, Any]) -> str | None:
    first, last = budget["first_code"], budget["last_code"]
    if first is None:
        return None
    return first if first == last else f"{first}–{last}"


def _days(days: list[dict[str, Any]]) -> dict[str, Any]:
    """The calendar, windowed around today and around the extras."""
    if not days:
        return {"shown": [], "note": "No mission days."}

    today_at = next(
        (index for index, day in enumerate(days) if day["state"] == "today"), None
    )
    if today_at is None:
        # Before the mission, or after it: the opening days and the closing
        # ones are what someone is asking about either way.
        near = set(range(min(len(days), DAYS_BEFORE))) | set(
            range(max(0, len(days) - DAYS_AFTER), len(days))
        )
    else:
        near = set(
            range(max(0, today_at - DAYS_BEFORE), min(len(days), today_at + DAYS_AFTER + 1))
        )

    # A day carrying an extra explains why its neighbours are lower, so it is
    # worth its line wherever it falls — but only after the days around today
    # are safe. A daily extra puts one on every day of the mission, and filling
    # the cap in date order would spend it all on MD-01 onwards and drop today,
    # which is the one day no answer can do without.
    keep = set(sorted(near)[:MAX_DAYS])
    for index, day in enumerate(days):
        if len(keep) >= MAX_DAYS:
            break
        if day["extras"]:
            keep.add(index)

    return {
        "shown": [
            {
                "day": day["code"],
                "date": day["date"],
                "when": day["state"],
                "planned": day["planned"],
                "revised_allowance": day["revised"],
                "extras": day["extras"] or None,
                "extras_are": day["extra_labels"] or None,
                "actual": day["actual"],
                "over_or_under": day["variance"],
                "status": day["status"],
            }
            for index, day in enumerate(days)
            if index in keep
        ],
        "note": (
            f"{len(days)} mission days in total; the days around today and "
            "every day carrying an extra are listed. The rest follow the same "
            "flat allowance."
        ),
    }
