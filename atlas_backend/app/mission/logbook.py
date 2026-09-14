"""The crew's own meter log: what a hand-read dial says, room by room and tap by tap.

WHY THIS EXISTS. Everything else on the dashboard comes from the habitat's
sensors through Grafana: one mains meter, one clean-water feed. That tells a
crew how much the habitat drew and nothing whatever about WHERE. The sub-meters
that would answer that are dials on a wall, so the answer arrives the only way
it can — somebody walks the rounds with a clipboard twice a day and writes the
numbers down. This module is what those numbers become.

It is a back-analysis, not a second telemetry feed. Its whole point is to be
derived from a different source than the charts, so the two can be put beside
each other and disagree out loud. A sum of sub-meters that comes to 12% under
the mains meter is a finding — a leak, a missed round, a mis-transcribed digit —
and it is only ever visible because the two figures were never allowed to
become the same figure.

WHAT IS STORED IS A READING, NOT A CONSUMPTION. A meter face shows a total that
only goes up. That is what the crew types, and consumption is the DIFFERENCE
between two of them. Storing the difference instead would be storing the crew's
mental arithmetic, and mental arithmetic taken at 06:30 in a habitat is exactly
the figure you want to be able to re-derive later when it looks wrong.

The convention, which every label on the page repeats:

    BOTH RESOURCES, two readings a day per dial, on the morning and evening
    rounds:

            morning block = evening reading  - morning reading   (the day)
            evening block = next morning     - evening reading   (the night)
            the day's total is therefore morning(d) -> morning(d+1).

Water was read once a day at first, and now is not. Two rounds on the taps as
well as on the rooms buys the same thing it buys on power — whether the draw
happened while the habitat was awake or overnight, which is the difference
between a crew that showers in the morning and a tap that drips all night. It
also means the two resources are read, entered and reported identically, so
there is one convention on this page instead of two.

Both run FORWARD, which has one consequence worth saying plainly rather than
hiding: a day's consumption is not known until the next day's reading is taken.
The last logged day is always open. The page says so on every figure it affects
rather than drawing a short bar that looks like a quiet day.

UNITS. Power is read in kWh and reported in kWh. Water is read in m3 — that is
what a water meter face shows — and reported in LITRES everywhere, because a
tap's daily draw in cubic metres is a number with three leading zeros and no
crew has ever compared two of those by eye.

KEYED BY MISSION DAY, not by calendar date. MD-03 is what is written at the top
of the clipboard page, so MD-03 is what is stored; moving the mission's start
date moves the whole log with it rather than stranding it, which is the
behaviour that matches how the crew filed it.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.core.errors import AtlasError
from app.mission import periods as per
from app.mission.plan import Mission, Plan, day_code

# -- what is metered -------------------------------------------------------

POWER = "power"
WATER = "water"
RESOURCES = (POWER, WATER)

# Both resources are read twice a day. A slot is a POSITION ON THE ROUND, not a
# clock time — the crew decides when the rounds happen, and pinning these to
# hours would invent a precision the clipboard does not have.
MORNING = "morning"
EVENING = "evening"

# Water's original single round. No longer offered, and kept named only so the
# one-line migration in `storage/database.py` that lifts old rows onto the
# morning round has something to refer to.
LEGACY_DAILY = "daily"

SLOTS: dict[str, tuple[str, ...]] = {
    POWER: (MORNING, EVENING),
    WATER: (MORNING, EVENING),
}

# A ROUND AND THE BLOCK IT OPENS ARE TWO DIFFERENT THINGS, and one name for
# both is the mistake this page invites. "Morning round" is the walk somebody
# takes to the dial — an event, and what the reading is filed under. "Daytime"
# is the CONSUMPTION between that walk and the next one, which is what every
# chart on the page is actually plotting.
#
# They were the same string once, so a bar labelled "Morning round" looked like
# it meant "the reading taken in the morning" rather than "everything drawn
# between the morning round and the evening one". Two names, used in two
# places: the round labels head the columns readings are typed into, and the
# block labels title every derived figure.
SLOT_LABEL = {
    MORNING: "Morning round",
    EVENING: "Evening round",
}

BLOCK_LABEL = {
    MORNING: "Daytime",
    EVENING: "Overnight",
}

# The span each block covers, spelled out. Printed wherever there is room for
# it, because it is the whole answer to "when is this calculated" — and the
# second one is the one that surprises people: the night is not closed until
# the NEXT morning's round is walked.
SLOT_COVERS = {
    MORNING: "morning round to evening round, the same day",
    EVENING: "evening round to the next morning's round",
}

# What a stored figure is typed in, and what it is shown in. The two differ for
# water on purpose; see the module docstring.
ENTRY_UNIT = {POWER: "kWh", WATER: "m³"}
REPORT_UNIT = {POWER: "kWh", WATER: "L"}
TO_REPORT = {POWER: 1.0, WATER: 1000.0}


@dataclass(frozen=True)
class Meter:
    """One dial on one wall."""

    key: str
    label: str
    # Which resource's log it appears in.
    resource: str
    # How the crew finds it: the number stencilled on the pipe, for water.
    code: str = ""
    # What it serves, for grouping a chart that would otherwise have more
    # slices than the palette has colours: sink, shower, toilet…
    group: str = ""
    group_label: str = ""
    # warm | cold | none. The half of the water story a per-tap chart cannot
    # tell on its own, and the one a crew can actually act on — warm water is
    # water AND the power that heated it.
    stream: str = "none"


WARM = "warm"
COLD = "cold"

# Which rooms and taps this habitat sub-meters is a fact about ITS wiring and
# plumbing, so the round is configuration rather than source: the crew maintains
# it in the interface, falling back to the habitat profile's `crew_log_meters:`.
# See `services/crew_meters.py`. These read it fresh, because the crew can add
# or rename a dial between one page load and the next.


def _specs(resource: str) -> tuple[Meter, ...]:
    from app.services import crew_meters

    return tuple(
        Meter(
            key=spec.key,
            label=spec.label,
            resource=spec.resource,
            code=spec.code,
            group=spec.group,
            group_label=spec.group_label,
            stream=spec.stream,
        )
        for spec in crew_meters.meters_for(resource)
    )


def meters_for(resource: str) -> tuple[Meter, ...]:
    """The dials on this habitat's round, in the order they are walked."""
    return _specs(resource)


def all_meters() -> dict[str, tuple[Meter, ...]]:
    return {POWER: _specs(POWER), WATER: _specs(WATER)}


def meter_by_key(resource: str, key: str) -> Meter | None:
    for meter in _specs(resource):
        if meter.key == key:
            return meter
    return None


RESOURCE_LABEL = {POWER: "Power by room", WATER: "Water by tap"}

# A hand-typed figure that is wrong by a factor of a thousand is the failure
# this catches — a crew typing litres into the m3 box. Generous, because a
# cumulative meter that has been on the wall for years legitimately reads high.
MAX_READING = 100_000_000.0

# -- the windows the analysis is cut into ----------------------------------

# The three questions the page answers, in the order it answers them. `days`
# is how many mission days back from the last logged one, or None for all of
# them.
WINDOWS: tuple[tuple[str, str, int | None], ...] = (
    ("day", "Latest logged day", 1),
    ("last3", "Last 3 logged days", 3),
    ("mission", "Since the mission started", None),
)

# Why a derived figure is missing. Kept apart from one another because they ask
# for different actions: `open` waits, `gap` needs somebody to go and read a
# dial, and `backwards` needs somebody to check what was typed.
OK = "ok"
OPEN = "open"
GAP = "gap"
BACKWARDS = "backwards"


# -- validation ------------------------------------------------------------


def check_resource(resource: str) -> str:
    if resource not in RESOURCES:
        raise AtlasError(
            f"Unknown resource {resource!r}. The crew log covers "
            f"{' and '.join(RESOURCES)}."
        )
    return resource


def check_meter(resource: str, key: str) -> Meter:
    meter = meter_by_key(check_resource(resource), key)
    if meter is None:
        raise AtlasError(
            f"There is no {resource} meter called {key!r} in the habitat. The "
            "log covers a fixed set of dials; a new one has to be added to the "
            "catalogue before it can be read into."
        )
    return meter


def check_slot(resource: str, slot: str) -> str:
    allowed = SLOTS[check_resource(resource)]
    if slot not in allowed:
        raise AtlasError(
            f"{resource.title()} is read on the {' and '.join(allowed)} round, "
            f"not on a {slot!r} one."
        )
    return slot


def check_day(day_index: Any, mission: Mission) -> int:
    """A mission day that exists, or a refusal naming the range that does."""
    try:
        index = int(day_index)
    except (TypeError, ValueError):
        raise AtlasError(
            f"The mission day must be a number like 3, got {day_index!r}."
        ) from None

    if not mission.is_declared:
        raise AtlasError(
            "No mission has been declared, so there is no MD-01 to file a "
            "reading against. Set the mission's start and length first — the "
            "log is laid out one row per mission day, and without a mission "
            "there are no days to lay out."
        )

    assert mission.days is not None
    if not 1 <= index <= mission.days:
        raise AtlasError(
            f"{day_code(index)} is outside this mission, which runs "
            f"{day_code(1)} to {day_code(mission.days)}."
        )
    return index


def check_value(value: Any, meter: Meter) -> float | None:
    """One meter reading, or None where the box was cleared.

    Clearing a box is how a mis-typed reading is withdrawn, and it must be
    possible: a wrong reading corrupts the two days either side of it, so
    "delete it and re-read the dial tomorrow" has to be an available move.
    """
    if value is None or value == "":
        return None

    try:
        number = float(value)
    except (TypeError, ValueError):
        raise AtlasError(
            f"The reading for {meter.label} must be a number, got {value!r}."
        ) from None

    if number != number or number in (float("inf"), float("-inf")):
        raise AtlasError(f"The reading for {meter.label} must be a real number.")
    if number < 0:
        raise AtlasError(
            f"The reading for {meter.label} is {number:g}. A meter face counts "
            "up from zero and cannot show a negative total — check whether a "
            "minus sign was typed by accident."
        )
    if number > MAX_READING:
        raise AtlasError(
            f"{number:g} is beyond anything a habitat sub-meter reads "
            f"(the cap is {MAX_READING:g}). Check the units: this box takes "
            f"{ENTRY_UNIT[meter.resource]}, the figure straight off the dial."
        )
    return round(number, 4)


# -- deriving --------------------------------------------------------------


def build_logbook(plan: Plan, readings: list[dict[str, Any]]) -> dict[str, Any]:
    """The whole crew-log page: the sheet, the deltas, and the distributions.

    Pure arithmetic over what is on disk — no habitat database is touched, so
    this page still works when Grafana is down, which is precisely when a crew
    is most likely to be reading dials by hand.
    """
    now = datetime.now(UTC)
    offset = plan.day_start_offset_minutes
    today = per.local_date(now, offset)
    mission = plan.mission

    envelope: dict[str, Any] = {
        "generated_at": per.iso(now),
        "day_start_label": f"00:00 {per.offset_label(offset)}",
        "mission": _mission_summary(mission, today),
        "resources": [],
    }

    stored = {
        (row["resource"], row["meter"], row["day_index"], row["slot"]): row
        for row in readings
        if meter_by_key(row["resource"], row["meter"]) is not None
    }

    days = _days(mission, today)
    envelope["days"] = days

    envelope["resources"] = [
        _resource(resource, mission, days, stored) for resource in RESOURCES
    ]
    return envelope


def _mission_summary(mission: Mission, today) -> dict[str, Any]:
    """Just enough of the mission to lay out a sheet and title it."""
    index = mission.day_index(today) if mission.is_declared else None
    inside = mission.is_declared and mission.contains(today)
    return {
        "is_declared": mission.is_declared,
        "name": mission.name,
        "start": None if mission.start is None else mission.start.isoformat(),
        "end": None if mission.end is None else mission.end.isoformat(),
        "days": mission.days,
        "today": today.isoformat(),
        "day_index": index if inside else None,
        "day_code": day_code(index) if inside and index is not None else None,
    }


def _days(mission: Mission, today) -> list[dict[str, Any]]:
    """Every mission day, whether or not anything has been logged against it.

    The full run, always — a 14-day mission gets 14 rows on MD-01, because a
    log sheet a crew cannot see the shape of is a log sheet with holes in it.
    """
    if not mission.is_declared:
        return []

    out: list[dict[str, Any]] = []
    for index, day in enumerate(mission.dates(), start=1):
        out.append(
            {
                "index": index,
                "code": day_code(index),
                "date": day.isoformat(),
                "state": (
                    "today" if day == today else ("past" if day < today else "future")
                ),
            }
        )
    return out


def _resource(
    resource: str,
    mission: Mission,
    days: list[dict[str, Any]],
    stored: dict[tuple[str, str, int, str], dict[str, Any]],
) -> dict[str, Any]:
    """One resource's sheet, its deltas, and everything summed off them."""
    meters = meters_for(resource)
    slots = SLOTS[resource]
    factor = TO_REPORT[resource]

    entries = [
        {
            "meter": key[1],
            "day_index": key[2],
            "slot": key[3],
            "value": row["value"],
            "updated_at": row["updated_at"],
        }
        for key, row in sorted(stored.items())
        if key[0] == resource
    ]

    usage: list[dict[str, Any]] = []
    issues: list[str] = []

    for meter in meters:
        for day in days:
            for slot in slots:
                cell = _block(resource, meter, day, slot, days, stored, factor)
                usage.append(cell)
                if cell["status"] == BACKWARDS:
                    # NAME BOTH READINGS AND PRINT BOTH FIGURES. This is the
                    # one message on the page that asks somebody to go and
                    # change something, and "reads lower at the end of MD-06"
                    # does not say which of the four boxes on those two days
                    # to look at. The closing round is the next MORNING for an
                    # evening block, which is exactly the part a reader gets
                    # wrong unaided.
                    closes_slot = EVENING if slot == MORNING else MORNING
                    issues.append(
                        f"{meter.label}: the {cell['closes_code']} "
                        f"{SLOT_LABEL[closes_slot].lower()} reads "
                        f"{_figure(cell['closes'])}, lower than the "
                        f"{day['code']} {SLOT_LABEL[slot].lower()}'s "
                        f"{_figure(cell['opens'])}. A "
                        "meter face counts up, so one of those two figures is "
                        f"mistyped — and the {BLOCK_LABEL[slot].lower()} block "
                        f"on {day['code']} is left out of every total until it "
                        "is fixed."
                    )

    per_day = _per_day(days, usage)
    latest = _latest_logged(per_day)

    return {
        "key": resource,
        "label": RESOURCE_LABEL[resource],
        "entry_unit": ENTRY_UNIT[resource],
        "unit": REPORT_UNIT[resource],
        "slots": [
            {
                "key": slot,
                "label": SLOT_LABEL[slot],
                "block_label": BLOCK_LABEL[slot],
                "covers": SLOT_COVERS[slot],
            }
            for slot in slots
        ],
        "meters": [
            {
                "key": meter.key,
                "label": meter.label,
                "code": meter.code,
                "group": meter.group,
                "group_label": meter.group_label,
                "stream": meter.stream,
            }
            for meter in meters
        ],
        "entries": entries,
        # Every block, including the ones with no figure. A cell that could not
        # be derived is the sheet's most useful mark — it says which dial to go
        # and read — so it travels with its reason attached rather than being
        # filtered out into an absence the page would have to re-infer.
        "usage": usage,
        "days": per_day,
        "latest_day": latest,
        "windows": [
            # `per_day` rather than `days`: a window has to know which of its
            # days are still waiting on a closing reading before it can say
            # whether its own total is final.
            _window(key, label, span, resource, meters, per_day, usage, latest)
            for key, label, span in WINDOWS
        ],
        "coverage": _coverage(meters, days, slots, resource, stored),
        "issues": issues,
    }


def _block(
    resource: str,
    meter: Meter,
    day: dict[str, Any],
    slot: str,
    days: list[dict[str, Any]],
    stored: dict[tuple[str, str, int, str], dict[str, Any]],
    factor: float,
) -> dict[str, Any]:
    """One meter's consumption over one block, from the two readings that bound it.

    The block a reading OPENS is the one it is filed under, so the morning
    round's figure is the one that produced the daylight hours — see the module
    docstring for why the convention runs forward.
    """
    index = day["index"]
    opens_at = (resource, meter.key, index, slot)

    # One convention for both resources: the morning round closes on that
    # evening's reading, and the evening round closes on the next morning's.
    closes_index = index if slot == MORNING else index + 1
    closes_at = (
        (resource, meter.key, index, EVENING)
        if slot == MORNING
        else (resource, meter.key, index + 1, MORNING)
    )

    opens = stored.get(opens_at)
    closes = stored.get(closes_at)
    beyond = closes_index > len(days)

    cell: dict[str, Any] = {
        "meter": meter.key,
        "day_index": index,
        "slot": slot,
        "amount": None,
        "status": OPEN,
        "opens": None if opens is None else opens["value"],
        "closes": None if closes is None else closes["value"],
        "closes_code": None if beyond else day_code(closes_index),
    }

    if opens is None or closes is None:
        # A block whose closing reading falls after the mission's last day can
        # never be closed, and neither can one whose closing round has not
        # happened yet. Both are `open`; a block bounded by two rounds that HAVE
        # happened and is still missing a figure is a `gap` somebody has to go
        # and fill.
        both_past = day["state"] == "past" and not beyond
        cell["status"] = GAP if both_past else OPEN
        return cell

    delta = closes["value"] - opens["value"]
    if delta < 0:
        cell["status"] = BACKWARDS
        return cell

    cell["amount"] = round(delta * factor, 4)
    cell["status"] = OK
    return cell


def _figure(value: float | None) -> str:
    """A stored reading, printed at the precision it was stored at.

    `%g` would round 20878.49 and 20878.5 to the same six-figure string — so a
    message whose entire job is to report that two figures differ would print
    them identically, and the reader would conclude the page was wrong rather
    than the reading. Readings are stored to four decimal places; this shows
    all of them, less the trailing zeros nobody needs to see.
    """
    if value is None:
        return "—"
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def _per_day(
    days: list[dict[str, Any]], usage: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Each mission day's total across every meter, with what it is missing."""
    by_day: dict[int, list[dict[str, Any]]] = {day["index"]: [] for day in days}
    for cell in usage:
        by_day[cell["day_index"]].append(cell)

    out: list[dict[str, Any]] = []
    for day in days:
        cells = by_day[day["index"]]
        measured = [cell for cell in cells if cell["amount"] is not None]
        out.append(
            {
                **day,
                "total": round(sum(cell["amount"] for cell in measured), 4)
                if measured
                else None,
                "blocks_logged": len(measured),
                "blocks_expected": len(cells),
                # A day still waiting on a closing reading is not a light day.
                # Every figure derived from it is provisional and says so.
                "complete": bool(cells) and len(measured) == len(cells),
            }
        )
    return out


def _latest_logged(per_day: list[dict[str, Any]]) -> int | None:
    """The most recent mission day anything has been derived for."""
    for day in reversed(per_day):
        if day["total"] is not None:
            return day["index"]
    return None


def _window(
    key: str,
    label: str,
    span: int | None,
    resource: str,
    meters: tuple[Meter, ...],
    days: list[dict[str, Any]],
    usage: list[dict[str, Any]],
    latest: int | None,
) -> dict[str, Any]:
    """One window of the analysis: the total, and how it splits.

    Every window ends at the LAST LOGGED DAY rather than at today. A window
    ending at a day nobody has read yet would report a fall in consumption
    every single morning, which is the most reliably misleading chart a
    dashboard can draw.
    """
    if latest is None or not days:
        indices: set[int] = set()
    elif span is None:
        indices = {day["index"] for day in days if day["index"] <= latest}
    else:
        indices = {index for index in range(latest - span + 1, latest + 1) if index >= 1}

    cells = [
        cell
        for cell in usage
        if cell["day_index"] in indices and cell["amount"] is not None
    ]
    total = round(sum(cell["amount"] for cell in cells), 4) if cells else None

    covered = sorted(
        {cell["day_index"] for cell in cells if cell["amount"] is not None}
    )
    incomplete = sorted(
        day["index"]
        for day in days
        if day["index"] in indices and not day.get("complete", False)
    )

    return {
        "key": key,
        "label": label,
        "first_code": day_code(min(indices)) if indices else None,
        "last_code": day_code(max(indices)) if indices else None,
        "days_covered": len(covered),
        "days_in_window": len(indices),
        "total": total,
        "per_day_mean": round(total / len(covered), 4)
        if total is not None and covered
        else None,
        "complete": bool(indices) and not incomplete,
        "meters": _shares(cells, total, meters, resource),
        "groups": _grouped(cells, total, meters, "group"),
        "streams": _grouped(cells, total, meters, "stream"),
        "slots": _by_slot(cells, total, resource),
    }


def _shares(
    cells: list[dict[str, Any]],
    total: float | None,
    meters: tuple[Meter, ...],
    resource: str,
) -> list[dict[str, Any]]:
    """Each meter's amount in the window, and its share of it, largest first.

    A meter with nothing logged is still listed, at zero — an absence in a
    ranked list reads as "not metered here", which is a different and wrong
    claim.
    """
    sums: dict[str, float] = {meter.key: 0.0 for meter in meters}
    logged: dict[str, bool] = {meter.key: False for meter in meters}
    for cell in cells:
        sums[cell["meter"]] += cell["amount"]
        logged[cell["meter"]] = True

    out = [
        {
            "key": meter.key,
            "label": meter.label,
            "code": meter.code,
            "amount": round(sums[meter.key], 4),
            "share": round(sums[meter.key] / total, 6)
            if total not in (None, 0)
            else None,
            "logged": logged[meter.key],
        }
        for meter in meters
    ]
    out.sort(key=lambda row: (-row["amount"], row["label"]))
    return out


def _grouped(
    cells: list[dict[str, Any]],
    total: float | None,
    meters: tuple[Meter, ...],
    field: str,
) -> list[dict[str, Any]]:
    """The same amounts collapsed onto what a meter serves, or onto warm/cold.

    Eleven taps is more slices than any palette this app is willing to spend a
    colour on — see `tokens/series.css` — and more than a reader can tell apart
    anyway. Grouped, water is five kinds of use or two temperatures, and both
    are questions a crew can act on.
    """
    index = {meter.key: meter for meter in meters}
    sums: dict[str, float] = {}
    labels: dict[str, str] = {}

    for meter in meters:
        value = getattr(meter, field)
        if not value or value == "none":
            continue
        sums.setdefault(value, 0.0)
        labels[value] = (
            meter.group_label if field == "group" else value.title()
        ) or value

    for cell in cells:
        meter = index[cell["meter"]]
        value = getattr(meter, field)
        if not value or value == "none":
            continue
        sums[value] += cell["amount"]

    out = [
        {
            "key": key,
            "label": labels[key],
            "amount": round(amount, 4),
            "share": round(amount / total, 6) if total not in (None, 0) else None,
        }
        for key, amount in sums.items()
    ]
    out.sort(key=lambda row: (-row["amount"], row["label"]))
    return out


def _by_slot(
    cells: list[dict[str, Any]], total: float | None, resource: str
) -> list[dict[str, Any]]:
    """The day's draw against the night's.

    Labelled with the BLOCK names, not the round names. These are amounts
    consumed between two walks, not the walks themselves, and a slice reading
    "Morning round" invites exactly the misreading that the figure belongs to
    the moment somebody stood at the dial.
    """
    sums = {slot: 0.0 for slot in SLOTS[resource]}
    for cell in cells:
        sums[cell["slot"]] += cell["amount"]

    return [
        {
            "key": slot,
            "label": BLOCK_LABEL[slot],
            "covers": SLOT_COVERS[slot],
            "amount": round(amount, 4),
            "share": round(amount / total, 6) if total not in (None, 0) else None,
        }
        for slot, amount in sums.items()
    ]


def _coverage(
    meters: tuple[Meter, ...],
    days: list[dict[str, Any]],
    slots: tuple[str, ...],
    resource: str,
    stored: dict[tuple[str, str, int, str], dict[str, Any]],
) -> dict[str, Any]:
    """How much of the sheet is filled in, and how much of it ought to be by now.

    Two denominators, deliberately. `expected` counts only the rounds that have
    already happened, and is the figure the crew is judged against; `total`
    counts the whole mission, and is the one that says how far through the log
    they are.
    """
    filled = 0
    expected_filled = 0
    expected = 0

    for meter in meters:
        for day in days:
            for slot in slots:
                present = (resource, meter.key, day["index"], slot) in stored
                filled += present
                if day["state"] == "past":
                    expected += 1
                    expected_filled += present

    return {
        "filled": filled,
        "total": len(meters) * len(days) * len(slots),
        "expected": expected,
        "expected_filled": expected_filled,
    }
