"""The crew's plan, on disk.

All the SQL for the mission plan lives here; everything above works in terms
of a `Plan` and never sees a cursor. Same arrangement, and same reasoning, as
`storage/conversation_repository.py`.

The plan is small, singular, and read on every page load, so there is no
caching: a plan someone edited in another tab and a plan on screen disagreeing
would be a far worse bug than a millisecond of SQLite.

WHAT IS STORED AND WHAT IS NOT. Three declared facts per mission, one ceiling
per resource, and the extras. Nothing derived — not a day's allowance, not a
cycle's, not what is left. Those are recomputed on every read by `dayplan.py`,
because a stored derivation is a figure that will eventually disagree with what
it was derived from, and the disagreement will be silent.

WHAT A ROW MEANS. A row is a figure the crew set. No row means nobody has. A
row with a NULL total is the crew saying they are not capping that resource —
which is a decision, and a different one from never having looked. Resetting
the plan deletes rows.
"""

import sqlite3
import time
import uuid
from datetime import date
from typing import Any

from app.core.errors import AtlasError
from app.core.logging import get_logger
from app.mission.plan import (
    CREW,
    DAILY,
    DEFAULT,
    RESOURCES,
    Extra,
    Mission,
    Plan,
    load_defaults,
    normalise_offset,
    parse_date,
)
from app.storage.database import connect

log = get_logger(__name__)

OFFSET_KEY = "day_start_offset_minutes"
NAME_KEY = "mission_name"
START_KEY = "mission_start"
DAYS_KEY = "mission_days"


def load_plan() -> Plan:
    """The plan in force: what the crew declared, over what we shipped."""
    defaults = load_defaults()

    totals: dict[str, float | None] = {resource: None for resource in RESOURCES}
    sources: dict[str, str] = {resource: DEFAULT for resource in RESOURCES}

    offset = defaults["day_start_offset_minutes"]
    updated_at: float | None = None

    with connect() as connection:
        rows = connection.execute(
            "SELECT resource, total, updated_at FROM mission_totals"
        ).fetchall()
        settings = connection.execute(
            "SELECT key, value, updated_at FROM mission_settings"
        ).fetchall()
        extra_rows = connection.execute(
            """
            SELECT id, resource, label, amount, kind, on_date, note,
                   created_at, updated_at
            FROM mission_extras
            """
        ).fetchall()

    for row in rows:
        resource = row["resource"]
        # A resource this build no longer offers is left on disk rather than
        # deleted — a downgrade should not destroy a plan — but it is not
        # shown, because there is nothing to show it against.
        if resource not in RESOURCES:
            continue
        totals[resource] = row["total"]
        sources[resource] = CREW
        updated_at = max(updated_at or 0.0, row["updated_at"])

    name = ""
    start: date | None = None
    days: int | None = None

    for row in settings:
        key, value = row["key"], row["value"]
        if key == OFFSET_KEY:
            offset = normalise_offset(value)
        elif key == NAME_KEY:
            name = value
        elif key == START_KEY:
            start = parse_date(value, "stored mission start")
        elif key == DAYS_KEY:
            days = _stored_days(value)
        else:
            continue
        updated_at = max(updated_at or 0.0, row["updated_at"])

    mission = Mission(name=name, start=start, days=days)
    extras = tuple(sorted((_as_extra(row) for row in extra_rows), key=_ordering))
    for row in extra_rows:
        updated_at = max(updated_at or 0.0, row["updated_at"])

    return Plan(
        totals=totals,
        sources=sources,
        day_start_offset_minutes=offset,
        mission=mission,
        extras=extras,
        suggested_daily=defaults["suggested_daily"],
        default_note=defaults["note"],
        updated_at=updated_at,
        warnings=_warnings(mission, extras),
    )


def _stored_days(value: str) -> int | None:
    """A stored mission length, or nothing if the row is unreadable.

    A corrupt length is treated as no mission rather than as an error: the
    setup form is a far better place to land than a 500, and re-declaring the
    mission overwrites the bad row on the way past.
    """
    try:
        days = int(value)
    except (TypeError, ValueError):
        log.warning("Unreadable mission length %r on disk; ignoring it", value)
        return None
    return days if days > 0 else None


def _ordering(extra: Extra) -> tuple[Any, ...]:
    """Daily first, then by the day they land on, then by name."""
    return (
        extra.resource,
        extra.kind != DAILY,
        extra.on_date or date.min,
        extra.label.lower(),
    )


def _as_extra(row: sqlite3.Row) -> Extra:
    return Extra(
        id=row["id"],
        resource=row["resource"],
        label=row["label"],
        amount=float(row["amount"]),
        kind=row["kind"],
        on_date=None if row["on_date"] is None else date.fromisoformat(row["on_date"]),
        note=row["note"] or "",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _warnings(mission: Mission, extras: tuple[Extra, ...]) -> list[str]:
    """Things about the stored plan worth saying before any arithmetic runs."""
    out: list[str] = []
    if not mission.is_declared:
        return out

    stranded = [
        extra
        for extra in extras
        if extra.on_date is not None and not mission.contains(extra.on_date)
    ]
    if stranded:
        # Reachable by moving the mission dates under extras that were valid
        # when they were entered. They are kept, not deleted — the crew put
        # them there — but they now come out of no day's allowance.
        names = ", ".join(sorted(extra.label for extra in stranded))
        out.append(
            f"{len(stranded)} extra(s) fall outside the mission's dates and "
            f"are budgeted nowhere: {names}. Move them onto a mission day or "
            "remove them."
        )
    return out


# -- writing ---------------------------------------------------------------


def save_totals(totals: dict[str, float | None]) -> None:
    """Record the crew's ceilings. Only the resources named are touched.

    A resource left out of the body keeps whatever it had, so one can be saved
    without sending the whole plan back and risking an edit made elsewhere in
    the meantime.
    """
    now = time.time()
    with connect() as connection:
        for resource, value in totals.items():
            connection.execute(
                """
                INSERT INTO mission_totals (resource, total, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(resource)
                DO UPDATE SET total = excluded.total,
                              updated_at = excluded.updated_at
                """,
                (resource, value, now),
            )

    log.info("Mission ceilings saved for %s", ", ".join(sorted(totals)))


def save_setting(key: str, value: str) -> None:
    """Record one of the plan's non-ceiling settings."""
    now = time.time()
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO mission_settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                                           updated_at = excluded.updated_at
            """,
            (key, value, now),
        )


def save_mission(mission: Mission) -> None:
    """Record when the mission runs and what it is called."""
    if mission.start is None or mission.days is None:
        raise AtlasError(
            "A mission needs both a first day and a length before it can be "
            "saved. Half a mission cannot be paced against."
        )
    save_setting(NAME_KEY, mission.name)
    save_setting(START_KEY, mission.start.isoformat())
    save_setting(DAYS_KEY, str(mission.days))
    log.info(
        "Mission %r set: %s for %d days",
        mission.name or "(unnamed)",
        mission.start,
        mission.days,
    )


def save_day_start(offset_minutes: int) -> None:
    save_setting(OFFSET_KEY, str(normalise_offset(offset_minutes)))


# -- extras ----------------------------------------------------------------


def add_extra(fields: dict[str, Any]) -> str:
    """Record one extra. Returns its id."""
    now = time.time()
    identifier = uuid.uuid4().hex

    with connect() as connection:
        connection.execute(
            """
            INSERT INTO mission_extras
                (id, resource, label, amount, kind, on_date, note,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                identifier,
                fields["resource"],
                fields["label"],
                fields["amount"],
                fields["kind"],
                None if fields["on_date"] is None else fields["on_date"].isoformat(),
                fields["note"],
                now,
                now,
            ),
        )

    log.info("Extra %r added (%s)", fields["label"], fields["resource"])
    return identifier


def update_extra(identifier: str, fields: dict[str, Any]) -> None:
    """Replace one extra's figures. Refuses an id that is not there."""
    with connect() as connection:
        changed = connection.execute(
            """
            UPDATE mission_extras
               SET resource = ?, label = ?, amount = ?, kind = ?, on_date = ?,
                   note = ?, updated_at = ?
             WHERE id = ?
            """,
            (
                fields["resource"],
                fields["label"],
                fields["amount"],
                fields["kind"],
                None if fields["on_date"] is None else fields["on_date"].isoformat(),
                fields["note"],
                time.time(),
                identifier,
            ),
        ).rowcount

    if not changed:
        raise AtlasError(
            "That extra is no longer in the plan — someone else may have "
            "removed it. Reload the mission page to see what is there now.",
        )


def delete_extra(identifier: str) -> None:
    """Forget one extra. Deleting one that is already gone is not an error."""
    with connect() as connection:
        connection.execute("DELETE FROM mission_extras WHERE id = ?", (identifier,))


def reset_plan() -> None:
    """Forget the mission, every ceiling, and every extra.

    NOT the crew's meter log. Those are readings somebody walked the habitat to
    take, and no amount of re-declaring a mission makes them untrue — the dial
    said what it said. The log has its own clearing action, on its own page,
    where whoever presses it knows what they are deleting.
    """
    with connect() as connection:
        connection.execute("DELETE FROM mission_totals")
        connection.execute("DELETE FROM mission_settings")
        connection.execute("DELETE FROM mission_extras")

    log.info("Mission plan cleared")


# -- the crew's meter log --------------------------------------------------


def load_readings() -> list[dict[str, Any]]:
    """Every hand-taken reading on disk, oldest mission day first.

    The whole log in one read. It is bounded by the habitat's fixed dials
    against the mission's declared length — a 30-day mission with eighteen
    meters is well under a thousand rows — so paging it would cost more code
    than it could ever save.
    """
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT resource, meter, day_index, slot, value, updated_at
            FROM mission_readings
            ORDER BY resource, day_index, meter, slot
            """
        ).fetchall()

    return [dict(row) for row in rows]


def save_reading(
    resource: str, meter: str, day_index: int, slot: str, value: float
) -> None:
    """Record one meter reading, replacing whatever was in that box."""
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO mission_readings
                (resource, meter, day_index, slot, value, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(resource, meter, day_index, slot)
            DO UPDATE SET value = excluded.value,
                          updated_at = excluded.updated_at
            """,
            (resource, meter, day_index, slot, value, time.time()),
        )


def delete_reading(resource: str, meter: str, day_index: int, slot: str) -> None:
    """Withdraw one reading. Clearing a box that is already empty is not an error."""
    with connect() as connection:
        connection.execute(
            """
            DELETE FROM mission_readings
             WHERE resource = ? AND meter = ? AND day_index = ? AND slot = ?
            """,
            (resource, meter, day_index, slot),
        )


def clear_readings(resource: str | None = None) -> None:
    """Forget the meter log — one resource's, or the whole of it."""
    with connect() as connection:
        if resource is None:
            connection.execute("DELETE FROM mission_readings")
        else:
            connection.execute(
                "DELETE FROM mission_readings WHERE resource = ?", (resource,)
            )

    log.info("Crew meter log cleared (%s)", resource or "everything")
