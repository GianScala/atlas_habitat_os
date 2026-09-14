"""The crew's meter log as a tool result: room by room, tap by tap.

The second of the two tools that do not touch the habitat's database. Where
`query.py` returns the crew's PLAN, this returns the crew's own MEASUREMENTS —
the numbers somebody wrote down off a dial on a wall.

WHY THIS IS A SEPARATE TOOL AND NOT MORE TELEMETRY. Everything else ATLAS can
reach comes from one place: the habitat's instruments, read through whichever
data-source adapter is configured. This comes from a clipboard. The two
accounts overlap - both of them measure the habitat's water and power - and
they are deliberately never merged,
because the whole value of a second account is that it was taken independently.
A sum of sub-meters that comes in 12% under the mains meter is a finding, and
it is only visible while the two remain two.

So every result from here is stamped with where it came from, and the reading
notes say plainly what the model must never do with it: add it to a telemetry
figure, present it as a sensor reading, or quietly prefer whichever of the two
better fits the question.

WHAT THIS ANSWERS THAT NOTHING ELSE CAN. The habitat's own instruments meter the
mains and the clean-water feed. Neither knows which ROOM drew the power or
which TAP drew the water, and no query against the database will ever say. Only
these dials do. "Which room uses the most power", "how much water does the
shower take", "is the warm feed the problem" — those questions have exactly one
source, and it is this one.

WHAT IS TRIMMED. The full sheet is a reading per dial per round per mission day
— several hundred figures, most of which are meter faces rather than
consumption. What comes back here is what was DERIVED from them: per-window
totals and shares, per-day totals, and the state of the record. One day's
individual blocks are available by asking for that day.
"""

from typing import Any

from app.mission import logbook as book
from app.mission import repository as repo

# The pieces of a window that are worth a model's tokens. `groups` is a water
# idea (what the tap serves) and `streams` is warm against cold; on power the
# same slot is the two rounds. Named per resource so the result reads as
# English rather than as a schema.
_SPLIT_LABEL = {
    "power": ("by_room", "by_time_of_day"),
    "water": ("by_tap", "by_temperature"),
}


def get_crew_meter_log(
    resource: str | None = None,
    meter: str | None = None,
    mission_day: int | None = None,
) -> dict[str, Any]:
    """Consumption per room and per tap, from the crew's hand-taken readings.

    Args:
        resource: limit to "power" (rooms) or "water" (taps). Omit for both.
        meter: limit to one room or tap. Accepts the name, the key, or the
            pipe code — "Kitchen", "shower_warm_4r", "4R".
        mission_day: a single mission day (1 is MD-01) to break out block by
            block. Omit for the summary.
    """
    plan = repo.load_plan()
    built = book.build_logbook(plan, repo.load_readings())
    mission = built["mission"]

    if not mission["is_declared"]:
        return {
            "source": "crew_meter_log",
            "mission_declared": False,
            "note": (
                "No mission has been declared, so the crew log has no mission "
                "days to file readings against and is empty. The crew declares "
                "a mission on the Dashboard's Mission view; the log itself is "
                "on Habitat consumption, behind 'Crew meter log'."
            ),
            "resources": [],
        }

    wanted = (resource or "").strip().lower()
    if wanted and wanted not in book.RESOURCES:
        raise ValueError(
            f"No crew-logged resource called {wanted!r}. Available: "
            f"{', '.join(book.RESOURCES)}."
        )

    rows = [
        row
        for row in built["resources"]
        if not wanted or row["key"] == wanted
    ]

    picked = _resolve_meter(meter, rows) if meter else None
    day = _resolve_day(mission_day, mission) if mission_day is not None else None

    return {
        "source": "crew_meter_log",
        "source_note": (
            "These figures are NOT from the habitat database and no query "
            "produced them. They are readings the crew took by hand off "
            "sub-meters on the wall, and the consumption below was derived by "
            "subtracting consecutive readings. This is the only source in the "
            "system that knows which room or which tap."
        ),
        "mission_declared": True,
        "generated_at": built["generated_at"],
        "day_boundary": built["day_start_label"],
        "mission": {
            "name": mission["name"],
            "start": mission["start"],
            "end": mission["end"],
            "days": mission["days"],
            "today": mission["today"],
            "today_is": mission["day_code"],
        },
        "resources": [_resource(row, picked, day) for row in rows],
        "reading_notes": _NOTES,
    }


def _resolve_meter(
    wanted: str, rows: list[dict[str, Any]]
) -> str:
    """One dial, named however the crew says it: key, label, or pipe code."""
    text = wanted.strip().lower()
    for row in rows:
        for entry in row["meters"]:
            if text in {
                entry["key"].lower(),
                entry["label"].lower(),
                entry["code"].lower(),
            }:
                return entry["key"]

    known = ", ".join(
        f"{entry['label']}" + (f" ({entry['code']})" if entry["code"] else "")
        for row in rows
        for entry in row["meters"]
    )
    raise ValueError(
        f"No crew-logged meter called {wanted!r}. The habitat's sub-meters "
        f"are: {known}."
    )


def _resolve_day(wanted: Any, mission: dict[str, Any]) -> int:
    try:
        index = int(wanted)
    except (TypeError, ValueError):
        raise ValueError(
            f"mission_day must be a number like 3, got {wanted!r}."
        ) from None

    days = mission["days"] or 0
    if not 1 <= index <= days:
        raise ValueError(
            f"MD-{index:02d} is outside this mission, which runs MD-01 to "
            f"MD-{days:02d}."
        )
    return index


def _resource(
    row: dict[str, Any], meter: str | None, day: int | None
) -> dict[str, Any]:
    key = row["key"]
    meters = {entry["key"]: entry for entry in row["meters"]}
    by_meter, by_split = _SPLIT_LABEL[key]

    out: dict[str, Any] = {
        "resource": key,
        "metered_by": (
            "seven sub-metered rooms"
            if key == "power"
            else "eleven individually metered taps"
        ),
        "unit": row["unit"],
        "read_off_the_dial_in": row["entry_unit"],
        "rounds_per_day": [slot["label"] for slot in row["slots"]],
        # The two blocks those rounds open, which is what every figure below
        # is actually split by. Named apart from the rounds because a round is
        # a walk to a dial and a block is the consumption between two walks.
        "consumption_blocks": [
            {"name": slot["block_label"], "covers": slot["covers"]}
            for slot in row["slots"]
        ],
        "how_consumption_is_derived": _DERIVATION[key],
        "meters": [
            {
                "name": entry["label"],
                "pipe_code": entry["code"] or None,
                "serves": entry["group_label"] or None,
                "temperature": entry["stream"] if entry["stream"] != "none" else None,
            }
            for entry in row["meters"]
            if meter is None or entry["key"] == meter
        ],
        "record": {
            "rounds_due_so_far": row["coverage"]["expected"],
            "rounds_written_down": row["coverage"]["expected_filled"],
            "latest_day_with_a_figure": _code(row["latest_day"]),
        },
        "windows": [
            _window(window, row, meters, meter, by_meter, by_split)
            for window in row["windows"]
        ],
        "days": [
            {
                "day": entry["code"],
                "date": entry["date"],
                "total": entry["total"],
                # A day still waiting on its closing reading is provisional and
                # can only go up. Reporting it as a low day is the single most
                # available misreading of this whole dataset.
                "still_open": entry["total"] is not None and not entry["complete"],
            }
            for entry in row["days"]
            if entry["total"] is not None
        ],
        "meters_with_nothing_logged": [
            meters[share["key"]]["label"]
            for share in _mission_window(row)["meters"]
            if not share["logged"] and (meter is None or share["key"] == meter)
        ],
        "issues": row["issues"],
    }

    if meter is not None:
        out["filtered_to_one_meter"] = meters[meter]["label"]
        out["that_meters_days"] = _meter_days(row, meter)

    if day is not None:
        out[f"MD-{day:02d}_block_by_block"] = _day_detail(row, meters, day, meter)

    return out


def _mission_window(row: dict[str, Any]) -> dict[str, Any]:
    return next(
        window for window in row["windows"] if window["key"] == "mission"
    )


def _window(
    window: dict[str, Any],
    row: dict[str, Any],
    meters: dict[str, dict[str, Any]],
    meter: str | None,
    by_meter: str,
    by_split: str,
) -> dict[str, Any]:
    """One window, with the two splits that are worth reading it by."""
    # Both resources are read on two rounds, so both get the day-against-night
    # split. Water gets warm-against-cold as well, which is the split it is
    # actually asked about — a warm figure is water AND the power that heated
    # it — so it is the one that takes the prominent name.
    split = window["streams"] if row["key"] == "water" else window["slots"]

    out: dict[str, Any] = {
        "window": window["label"],
        "covers": _covers(window),
        "days_measured": window["days_covered"],
        "total": window["total"],
        "per_day_mean": window["per_day_mean"],
        "every_block_closed": window["complete"],
        by_meter: [
            {
                "name": meters[share["key"]]["label"],
                "amount": share["amount"],
                "share_pct": None if share["share"] is None else round(share["share"] * 100, 1),
            }
            for share in window["meters"]
            if share["logged"] and (meter is None or share["key"] == meter)
        ],
        by_split: [
            {
                "name": part["label"],
                "amount": part["amount"],
                "share_pct": None if part["share"] is None else round(part["share"] * 100, 1),
            }
            for part in split
            if part["amount"] > 0
        ],
    }

    if row["key"] == "water":
        out["by_what_it_serves"] = [
            {
                "name": part["label"],
                "amount": part["amount"],
                "share_pct": None if part["share"] is None else round(part["share"] * 100, 1),
            }
            for part in window["groups"]
            if part["amount"] > 0
        ]
        out["by_time_of_day"] = [
            {
                "name": part["label"],
                "amount": part["amount"],
                "share_pct": None if part["share"] is None else round(part["share"] * 100, 1),
            }
            for part in window["slots"]
            if part["amount"] > 0
        ]

    return out


def _covers(window: dict[str, Any]) -> str | None:
    first, last = window["first_code"], window["last_code"]
    if first is None:
        return None
    return first if first == last else f"{first}–{last}"


def _meter_days(row: dict[str, Any], meter: str) -> list[dict[str, Any]]:
    """One dial's own day-by-day series, summed over its blocks."""
    totals: dict[int, float] = {}
    for cell in row["usage"]:
        if cell["meter"] != meter or cell["amount"] is None:
            continue
        totals[cell["day_index"]] = totals.get(cell["day_index"], 0.0) + cell["amount"]

    return [
        {
            "day": entry["code"],
            "date": entry["date"],
            "total": round(totals[entry["index"]], 4),
        }
        for entry in row["days"]
        if entry["index"] in totals
    ]


def _day_detail(
    row: dict[str, Any],
    meters: dict[str, dict[str, Any]],
    day: int,
    meter: str | None,
) -> list[dict[str, Any]]:
    """One mission day, block by block, with why anything is missing."""
    out = []
    for cell in row["usage"]:
        if cell["day_index"] != day:
            continue
        if meter is not None and cell["meter"] != meter:
            continue
        out.append(
            {
                "meter": meters[cell["meter"]]["label"],
                "block": _BLOCK_NAME[cell["slot"]],
                "amount": cell["amount"],
                "state": _STATE[cell["status"]],
            }
        )
    return out


def _code(index: int | None) -> str | None:
    return None if index is None else f"MD-{index:02d}"


_DERIVATION = {
    "power": (
        "Two readings a day per room. The morning block is that evening's "
        "reading minus the morning's; the evening block is the NEXT morning's "
        "reading minus the evening's. So a day runs from one morning round to "
        "the next, and the last day logged is always still open."
    ),
    "water": (
        "Two readings a day per tap, in cubic metres off the dial, reported "
        "here in LITRES. The morning block is that evening's reading minus "
        "the morning's; the evening block is the NEXT morning's reading minus "
        "the evening's. So a day runs from one morning round to the next, and "
        "the last day logged is always still open."
    ),
}

# What each block is called in a result. Matches the page exactly, so a crew
# member reading an answer and then opening the log sees one set of words.
_BLOCK_NAME = {"morning": "daytime", "evening": "overnight"}

_STATE = {
    "ok": "measured",
    "open": "waiting on the reading that closes it — not a low block",
    "gap": "both rounds happened and one reading was never written down",
    "backwards": (
        "the closing reading is lower than the opening one, so one of the two "
        "is mistyped; both are excluded from every total"
    ),
}

_NOTES = [
    "This is the crew's own account, taken by hand. It is NOT the habitat "
    "database. Say where a figure came from whenever you quote one, and never "
    "present these as sensor readings.",
    "Never add a figure from here to a figure from the telemetry tools, and "
    "never average the two. They are two independent measurements of the same "
    "habitat, and the point of having both is that they can be compared.",
    "The habitat's own instruments meter the mains and the clean-water feed "
    "only. For which ROOM or which TAP, this is the only source there is.",
    "A day marked still_open is waiting on its closing reading and can only "
    "go up. It is not a quiet day, and it must not be quoted as a total.",
    "A meter listed in meters_with_nothing_logged has no readings at all in "
    "the window. That is a gap in the record, not a room that used none.",
    "Water is entered in m³ and every figure here is already converted to "
    "litres. Do not convert again.",
]
