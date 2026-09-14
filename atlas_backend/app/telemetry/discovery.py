"""Schema discovery — the database describes itself.

Nothing about the habitat's schema is hardcoded. Measurements, tag keys, tag
values, and field keys are all read from InfluxDB at runtime, cached for the
life of the process because a schema does not change mid-session.

This is what makes it possible to answer "is there a sensor for X" honestly:
the answer comes from a search over what actually exists, not from a list
somebody wrote down once.
"""

from typing import Any

from app.core.errors import DatasourceError
from app.datasource import get_data_source
from app.telemetry.units import unit_for
from app.telemetry.zones import (
    LOCATION_TAG_KEYS,
    case_variants,
    is_internal,
    zone_names_for,
)

_CACHE: dict[str, Any] = {}


def reset_cache() -> None:
    """Forget everything discovered. Used by tests and the refresh endpoint."""
    _CACHE.clear()


# --------------------------------------------------------------------------
# Measurements
# --------------------------------------------------------------------------


def discover(refresh: bool = False) -> dict:
    """Every measurement, split into habitat sensors vs the DB's own metrics."""
    if refresh or "measurements" not in _CACHE:
        names = get_data_source().measurements()
        _CACHE["measurements"] = {
            "query": "list measurements",
            "habitat": [n for n in names if not is_internal(n)],
            "internal_count": sum(1 for n in names if is_internal(n)),
            "total": len(names),
        }
    return _CACHE["measurements"]


def list_measurements() -> dict:
    """What this database holds, with InfluxDB's own metrics separated out."""
    found = discover()
    return {
        "query": found["query"],
        "data": found["habitat"] or None,
        "count": len(found["habitat"]),
        "note": (
            f"{found['internal_count']} further measurements are InfluxDB's own "
            "internal metrics and are not habitat sensors."
        ),
    }


# --------------------------------------------------------------------------
# Whole-schema index — what makes searching by concept possible
# --------------------------------------------------------------------------


def schema_index(refresh: bool = False) -> dict[str, dict[str, list[str]]]:
    """Field and tag keys for EVERY measurement, in two queries.

    InfluxQL's SHOW FIELD KEYS / SHOW TAG KEYS without a FROM clause return one
    series per measurement, so the whole schema costs two round trips rather
    than two per measurement.
    """
    if refresh or "index" not in _CACHE:
        raw = get_data_source().schema_index()
        if not raw:
            # The adapter cannot answer the whole schema cheaply; the caller
            # falls back to per-measurement discovery.
            _CACHE["index"] = {}
        else:
            _CACHE["index"] = {
                name: {
                    "fields": list(entry.get("fields", [])),
                    "tags": list(entry.get("tags", [])),
                }
                for name, entry in raw.items()
                if not is_internal(name)
            }
    return _CACHE["index"]


def find_measurements(keyword: str) -> dict:
    """Search the whole schema for a concept — names, fields, and tag keys.

    Use this before concluding that nothing measures something. 'power' finds
    both Electricity (powerActive, the mains meter) and Energy (power_active,
    the per-room submeters); 'room' finds every measurement carrying a
    Location tag.

    Matching one measurement's schema tells you nothing about the other
    thirty-six, which is exactly the mistake this exists to prevent.
    """
    needle = str(keyword).strip().lower()
    if not needle:
        raise ValueError("find_measurements needs a keyword.")

    index = schema_index()
    if not index:  # SHOW without FROM unsupported — fall back, slower
        index = {
            name: {
                "fields": [f["field"] for f in field_keys(name)],
                "tags": tag_keys(name),
            }
            for name in discover()["habitat"]
        }

    hits = []
    for measurement, entry in sorted(index.items()):
        why: list[str] = []
        if needle in measurement.lower():
            why.append("measurement name")
        matched_fields = [f for f in entry["fields"] if needle in f.lower()]
        matched_tags = [t for t in entry["tags"] if needle in t.lower()]
        if matched_fields:
            why.append(f"fields {matched_fields}")
        if matched_tags:
            why.append(f"tag keys {matched_tags}")
        if why:
            hits.append(
                {
                    "measurement": measurement,
                    "matched_on": why,
                    "fields": entry["fields"],
                    "tag_keys": entry["tags"],
                }
            )

    if hits:
        note = f"Searched all {len(index)} habitat measurements. {len(hits)} matched."
    else:
        note = (
            f"Searched all {len(index)} habitat measurements. None matched by "
            "name, field, or tag key — but a measurement may still hold this "
            "under a different word. Check list_measurements before reporting "
            "absence."
        )

    return {
        "query": "SHOW FIELD KEYS + SHOW TAG KEYS (whole-schema search)",
        "keyword": keyword,
        "data": hits or None,
        "searched_measurements": len(index),
        "note": note,
    }


# --------------------------------------------------------------------------
# Per-measurement schema
# --------------------------------------------------------------------------


def tag_keys(measurement: str) -> list[str]:
    """Tag keys on one measurement."""
    key = f"tagkeys:{measurement}"
    if key not in _CACHE:
        _CACHE[key] = get_data_source().tag_keys(measurement)
    return _CACHE[key]


def field_keys(measurement: str) -> list[dict]:
    """Field keys and their types on one measurement."""
    key = f"fieldkeys:{measurement}"
    if key not in _CACHE:
        _CACHE[key] = get_data_source().field_keys(measurement)
    return _CACHE[key]


def tag_values(measurement: str, tag_key: str) -> list[str]:
    """Every value a tag key takes on one measurement."""
    key = f"tagvalues:{measurement}:{tag_key}"
    if key not in _CACHE:
        _CACHE[key] = sorted(set(get_data_source().tag_values(measurement, tag_key)))
    return _CACHE[key]


def default_location_key(measurement: str) -> str | None:
    """Which tag key names a place on this measurement, if any."""
    keys = tag_keys(measurement)
    for candidate in LOCATION_TAG_KEYS:
        if candidate in keys:
            return candidate
    return None


def default_field(measurement: str) -> str:
    """The field to read when the caller did not name one."""
    fields = [f["field"] for f in field_keys(measurement)]
    if not fields:
        raise DatasourceError(f"{measurement} has no field keys.")
    return "value" if "value" in fields else fields[0]


# --------------------------------------------------------------------------
# Assembled views
# --------------------------------------------------------------------------


def _described_fields(measurement: str) -> list[dict]:
    described = []
    for entry in field_keys(measurement):
        unit, source = unit_for(measurement, entry["field"])
        described.append(
            {
                "field": entry["field"],
                "type": entry["type"],
                "unit": unit,
                "unit_source": source,
            }
        )
    return described


def describe(measurement: str) -> dict:
    """Everything the database knows about one measurement.

    Call this before querying anything unfamiliar — it reports the real tag
    keys, tag values, and field keys rather than assuming a schema.
    """
    keys = tag_keys(measurement)
    fields = _described_fields(measurement)
    location_key = default_location_key(measurement)

    out: dict[str, Any] = {
        "measurement": measurement,
        "tag_keys": keys,
        "fields": fields,
        "location_tag_key": location_key,
        "default_field": default_field(measurement) if fields else None,
        "data": bool(fields) or None,
    }

    if location_key:
        values = tag_values(measurement, location_key)
        out["locations"] = values
        out["zone_names"] = zone_names_for(values)
        variants = case_variants(values)
        if variants:
            out["case_variant_warning"] = (
                "These tag values differ only by capitalisation and hold "
                "SEPARATE data. Queries here cover all variants and report "
                "which were matched."
            )
            out["case_variants"] = variants

    for key in keys:
        if key != location_key:
            out.setdefault("other_tags", {})[key] = tag_values(measurement, key)

    return out


def list_locations(measurement: str) -> dict:
    """Which places report this measurement, by whatever tag key it uses."""
    key = default_location_key(measurement)
    if key is None:
        return {
            "measurement": measurement,
            "query": f"tag keys of {measurement}",
            "data": None,
            "note": (
                f"{measurement} has no location-like tag. "
                f"Its tags are: {tag_keys(measurement)}"
            ),
        }

    values = tag_values(measurement, key)
    out = {
        "measurement": measurement,
        "tag_key": key,
        "query": f"values of tag {key!r} on {measurement}",
        "data": values or None,
        "zone_names": zone_names_for(values),
    }
    variants = case_variants(values)
    if variants:
        out["case_variants"] = variants
    return out


def list_fields(measurement: str) -> dict:
    """Field keys and types for a measurement, with units where known."""
    return {
        "measurement": measurement,
        "query": f"fields of {measurement}",
        "data": _described_fields(measurement) or None,
    }
