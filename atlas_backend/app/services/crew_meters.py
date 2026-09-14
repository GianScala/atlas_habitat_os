"""The dials the crew walks round and reads by hand.

Which rooms are sub-metered, and which taps have a meter on them, is a fact
about a habitat's wiring and plumbing — not about ATLAS. One station meters
seven rooms; another meters three and calls the kitchen `2B`. So the list is
not shipped in the source. It resolves in three steps:

    1. rows in `crew_meters`     the crew maintains the round in the interface
    2. the habitat profile       `crew_log_meters:` in its YAML
    3. nothing                   the log simply has no dials, and says so

Editing is wholesale: the first time the crew saves, the profile's list is
written into the database and becomes theirs to add to, rename, reorder, and
remove. Readings already logged are keyed by the meter's `key`, so renaming a
meter keeps its history and removing one hides it without deleting anything.
"""

import re
import time
from dataclasses import dataclass

from app.core.errors import AtlasError
from app.core.logging import get_logger
from app.habitat import profile
from app.storage.database import connect

log = get_logger(__name__)

POWER = "power"
WATER = "water"
RESOURCES = (POWER, WATER)

WARM = "warm"
COLD = "cold"
STREAMS = (WARM, COLD, "none")

_KEY = re.compile(r"^[a-z0-9_]+$")


@dataclass(frozen=True)
class MeterSpec:
    """One dial, as configured. Mirrors `mission.logbook.Meter`."""

    key: str
    label: str
    resource: str
    code: str = ""
    group: str = ""
    group_label: str = ""
    stream: str = "none"


def check_resource(resource: str) -> str:
    if resource not in RESOURCES:
        raise AtlasError(
            f"Unknown resource {resource!r}. Use {' or '.join(RESOURCES)}."
        )
    return resource


def _slug(label: str) -> str:
    """A stable key from a label, for a meter the crew added by name."""
    base = re.sub(r"[^a-z0-9]+", "_", str(label).strip().lower()).strip("_")
    return base or "meter"


def _from_profile() -> dict[str, list[MeterSpec]]:
    """The round as the habitat profile declares it."""
    declared = profile().crew_log_meters or {}
    out: dict[str, list[MeterSpec]] = {POWER: [], WATER: []}
    for resource in RESOURCES:
        for entry in declared.get(resource) or []:
            if not isinstance(entry, dict) or not entry.get("label"):
                continue
            key = str(entry.get("key") or _slug(entry["label"]))
            out[resource].append(
                MeterSpec(
                    key=key,
                    label=str(entry["label"]),
                    resource=resource,
                    code=str(entry.get("code", "")),
                    group=str(entry.get("group", "")),
                    group_label=str(entry.get("group_label", "")),
                    stream=str(entry.get("stream", "none")),
                )
            )
    return out


def _stored() -> dict[str, list[MeterSpec]]:
    """The round as the crew has edited it, or empty if they never have."""
    try:
        with connect() as connection:
            rows = connection.execute(
                "SELECT resource, key, label, code, grouping, group_label, stream "
                "FROM crew_meters ORDER BY resource, position, key"
            ).fetchall()
    except Exception as exc:  # pragma: no cover - config, not a rule
        log.warning("Could not read the crew meter round: %s", exc)
        return {POWER: [], WATER: []}

    out: dict[str, list[MeterSpec]] = {POWER: [], WATER: []}
    for row in rows:
        if row["resource"] not in RESOURCES:
            continue
        out[row["resource"]].append(
            MeterSpec(
                key=row["key"],
                label=row["label"],
                resource=row["resource"],
                code=row["code"] or "",
                group=row["grouping"] or "",
                group_label=row["group_label"] or "",
                stream=row["stream"] or "none",
            )
        )
    return out


def meters() -> dict[str, list[MeterSpec]]:
    """The round in force: the crew's list where they have one, else the profile's."""
    stored = _stored()
    if stored[POWER] or stored[WATER]:
        return stored
    return _from_profile()


def meters_for(resource: str) -> list[MeterSpec]:
    return meters().get(check_resource(resource), [])


def is_customised() -> bool:
    """Has the crew taken the round over from the profile?"""
    stored = _stored()
    return bool(stored[POWER] or stored[WATER])


def save(resource: str, entries: list[dict]) -> list[MeterSpec]:
    """Replace one resource's round with this list, in this order.

    Wholesale rather than per-row: the round is an ordered walk, and an edit is
    "here is the round now". The other resource's list is left alone, and is
    seeded from the profile if the crew had never edited either — otherwise
    saving the water taps would silently delete the power rooms.
    """
    check_resource(resource)

    seen: set[str] = set()
    specs: list[MeterSpec] = []
    for entry in entries:
        label = str(entry.get("label") or "").strip()
        if not label:
            raise AtlasError("Every meter needs a name somebody can read.")
        if len(label) > 120:
            raise AtlasError(f"The name {label[:40]!r}… is too long.")

        key = str(entry.get("key") or "").strip() or _slug(label)
        if not _KEY.match(key):
            raise AtlasError(
                f"Meter id {key!r} may use only lowercase letters, digits and "
                "underscores."
            )
        if key in seen:
            raise AtlasError(f"Two meters share the id {key!r}. Ids must be unique.")
        seen.add(key)

        stream = str(entry.get("stream") or "none")
        if stream not in STREAMS:
            raise AtlasError(f"Unknown stream {stream!r}. Use warm, cold, or none.")

        specs.append(
            MeterSpec(
                key=key,
                label=label,
                resource=resource,
                code=str(entry.get("code") or "").strip(),
                group=str(entry.get("group") or "").strip(),
                group_label=str(entry.get("group_label") or "").strip(),
                stream=stream,
            )
        )

    # Seed the untouched resource from the profile the first time, so taking
    # over one list does not empty the other.
    other = [r for r in RESOURCES if r != resource][0]
    existing = _stored()
    other_specs = existing[other] or (
        _from_profile()[other] if not (existing[POWER] or existing[WATER]) else []
    )

    now = time.time()
    with connect() as connection:
        connection.execute("DELETE FROM crew_meters WHERE resource = ?", (resource,))
        _write(connection, specs, now)
        if other_specs and not existing[other]:
            _write(connection, other_specs, now)
    return specs


def _write(connection, specs: list[MeterSpec], now: float) -> None:
    for position, spec in enumerate(specs):
        connection.execute(
            "INSERT INTO crew_meters (resource, key, label, code, grouping, "
            "group_label, stream, position, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(resource, key) DO UPDATE SET label = excluded.label, "
            "code = excluded.code, grouping = excluded.grouping, "
            "group_label = excluded.group_label, stream = excluded.stream, "
            "position = excluded.position, updated_at = excluded.updated_at",
            (
                spec.resource,
                spec.key,
                spec.label,
                spec.code,
                spec.group,
                spec.group_label,
                spec.stream,
                position,
                now,
            ),
        )


def reset(resource: str | None = None) -> None:
    """Hand the round back to the habitat profile.

    Logged readings are keyed by meter id and are NOT deleted — they reappear
    if the meter is added back under the same id.
    """
    with connect() as connection:
        if resource is None:
            connection.execute("DELETE FROM crew_meters")
        else:
            connection.execute(
                "DELETE FROM crew_meters WHERE resource = ?", (check_resource(resource),)
            )
