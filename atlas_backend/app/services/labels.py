"""What the crew calls the things the database names.

A habitat's database speaks whatever vocabulary its engineers chose. One
station tags the sleeping quarters `Container3`, another `2B`, another
`crew_room`. None of those is wrong, and none of them is what a crew wants to
read on a chart.

So ATLAS separates the two: the tag value is what queries use and is never
changed, and the DISPLAY NAME is what the interface shows. A name resolves in
three steps, most specific first:

    1. a row in `display_labels`   the crew renamed it in the interface
    2. the habitat profile         `zone_names:` in its YAML
    3. the raw value               nothing has renamed it, so show it as it is

Nothing here writes to the habitat database. Renaming is a read-only
convenience, and every answer still cites the real tag the query matched.
"""

import time

from app.core.errors import AtlasError
from app.core.logging import get_logger
from app.habitat import profile
from app.storage.database import connect

log = get_logger(__name__)

LOCATION = "location"
MEASUREMENT = "measurement"
KINDS = (LOCATION, MEASUREMENT)

# Where a name came from, reported to the interface so a reader can tell a
# name somebody chose from one the database supplied.
CREW = "crew"
PROFILE = "profile"
RAW = "raw"

# Overrides, cached for the life of the process and dropped on every write.
# Read on every chart series and every prompt, so a database round trip per
# lookup would be paid thousands of times over a dashboard.
_cache: dict[tuple[str, str], str] | None = None


def check_kind(kind: str) -> str:
    if kind not in KINDS:
        raise AtlasError(f"Unknown kind {kind!r}. Use one of: {', '.join(KINDS)}.")
    return kind


def overrides() -> dict[tuple[str, str], str]:
    """Every crew-chosen name, by (kind, key).

    A failure to read them is not allowed to take a page down: the interface
    falls back to the profile's names, which is exactly what it showed before
    anyone renamed anything.
    """
    global _cache
    if _cache is None:
        try:
            with connect() as connection:
                rows = connection.execute(
                    "SELECT kind, key, label FROM display_labels"
                ).fetchall()
            _cache = {(row["kind"], row["key"]): row["label"] for row in rows}
        except Exception as exc:  # pragma: no cover - a preference, not a rule
            log.warning("Could not read display labels: %s", exc)
            return {}
    return _cache


def reset_cache() -> None:
    """Forget the cached overrides. Called after every write."""
    global _cache
    _cache = None


def display_name(key: str, kind: str = LOCATION) -> str:
    """What to SHOW for a tag value or measurement name.

    Never raises and never returns empty: an unknown key is its own name, which
    is the honest thing to show for a place nobody has named yet.
    """
    if not key:
        return key
    crew = overrides().get((kind, key))
    if crew:
        return crew
    if kind == LOCATION:
        named = profile().zone_names.get(key)
        if named:
            return named
    return key


def source_of(key: str, kind: str = LOCATION) -> str:
    """Where this name came from: crew | profile | raw."""
    if overrides().get((kind, key)):
        return CREW
    if kind == LOCATION and profile().zone_names.get(key):
        return PROFILE
    return RAW


def names_for(keys: list[str], kind: str = LOCATION) -> dict[str, str]:
    """Display names for these keys, for the ones that have a real name.

    Keeps the shape `zones.zone_names_for` had: only keys with a name other
    than themselves appear, so a caller can tell "renamed" from "as-is".
    """
    out: dict[str, str] = {}
    for key in keys:
        name = display_name(key, kind)
        if name != key:
            out[key] = name
    return out


def set_label(kind: str, key: str, label: str) -> None:
    """Rename one thing. An empty label clears the override."""
    check_kind(kind)
    key = str(key).strip()
    if not key:
        raise AtlasError("A name needs something to name.")

    label = str(label or "").strip()
    if not label:
        clear_label(kind, key)
        return
    if len(label) > 120:
        raise AtlasError("That name is too long — keep it under 120 characters.")

    with connect() as connection:
        connection.execute(
            "INSERT INTO display_labels (kind, key, label, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(kind, key) DO UPDATE SET label = excluded.label, "
            "updated_at = excluded.updated_at",
            (kind, key, label, time.time()),
        )
    reset_cache()


def clear_label(kind: str, key: str) -> None:
    """Drop a crew name, falling back to the profile's or the raw value."""
    check_kind(kind)
    with connect() as connection:
        connection.execute(
            "DELETE FROM display_labels WHERE kind = ? AND key = ?", (kind, key)
        )
    reset_cache()


def catalogue() -> dict:
    """What this habitat's database holds, and what each thing is called here.

    Everything comes from the connected database: the measurements and the
    location tag values are discovered at request time, so a habitat sees its
    own vocabulary the moment it connects and never a list somebody kept by
    hand.

    A database that cannot be read is a state, not a failure. It reports
    `connected: false` and why, so the page can say "nothing is loaded yet"
    instead of showing an error or, worse, an empty table that looks like a
    habitat with no sensors.
    """
    from app.datasource import get_data_source
    from app.telemetry import discovery

    try:
        source = get_data_source().describe()
    except AtlasError as exc:
        return _disconnected(exc.message, "")

    try:
        found = discovery.discover()["habitat"]
    except AtlasError as exc:
        return _disconnected(exc.message, source)

    measurements: list[dict] = []
    locations: dict[str, list[str]] = {}

    for measurement in found:
        measurements.append(
            {
                "key": measurement,
                "label": display_name(measurement, MEASUREMENT),
                "source": source_of(measurement, MEASUREMENT),
            }
        )
        try:
            location_key = discovery.default_location_key(measurement)
            if not location_key:
                continue
            for value in discovery.tag_values(measurement, location_key):
                locations.setdefault(value, []).append(measurement)
        except AtlasError:
            continue

    return {
        "connected": True,
        "detail": None,
        "source": source,
        "measurements": measurements,
        "locations": [
            {
                "key": value,
                "label": display_name(value, LOCATION),
                "source": source_of(value, LOCATION),
                "seen_in": sorted(seen),
            }
            for value, seen in sorted(locations.items())
        ],
    }


def _disconnected(detail: str, source: str) -> dict:
    """No database to read, and the reason why."""
    log.info("Nomenclature has no database to read: %s", detail)
    return {
        "connected": False,
        "detail": detail,
        "source": source,
        "measurements": [],
        "locations": [],
    }
