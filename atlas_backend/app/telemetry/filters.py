"""Turning a question's terms into WHERE clauses, and the result envelope.

Sits between the pure string helpers in influxql.py and the schema knowledge
in discovery.py, because building a location filter needs both.
"""

from typing import Any

from app.core.errors import QueryError
from app.datasource.query import TagFilter, TimeWindow
from app.telemetry import influxql as ql
from app.telemetry.discovery import (
    default_field,
    default_location_key,
    field_keys,
    tag_keys,
    tag_values,
)
from app.telemetry.units import unit_for


def build_filters(
    measurement: str,
    location: str | None,
    tags: dict | None,
) -> tuple[list[TagFilter], dict, list[str]]:
    """Structured tag filters from a location and/or explicit tag filters.

    Database-neutral: returns `TagFilter`s the active adapter renders into its
    own dialect, not InfluxQL strings. `location` is matched against the
    measurement's own location-like tag key and covers every capitalisation
    variant of that value — so asking for the airlock reads both 'AirLock' and
    'Airlock' rather than silently half of it.

    Returns (filters, tags applied, tag values actually matched).
    """
    filters: list[TagFilter] = []
    applied: dict[str, str] = {}
    matched: list[str] = []

    if location:
        key = default_location_key(measurement)
        if key is None:
            raise QueryError(
                f"{measurement} has no location-like tag key (its tags are "
                f"{tag_keys(measurement)}). Use the tags argument instead."
            )

        known = tag_values(measurement, key)
        variants = [v for v in known if v.lower() == location.lower()]
        if not variants:
            # Unknown value: query it literally so the caller sees an empty
            # result rather than us silently substituting something else.
            variants = [location]

        matched = variants
        filters.append(TagFilter(key=key, values=tuple(variants)))
        applied[key] = location

    for key, value in (tags or {}).items():
        filters.append(TagFilter(key=key, values=(str(value),)))
        applied[key] = str(value)

    return filters, applied, matched


def build_where(
    measurement: str,
    location: str | None,
    tags: dict | None,
) -> tuple[list[str], dict, list[str]]:
    """InfluxQL WHERE clauses — the string rendering of `build_filters`.

    Kept for the advanced analyses (tank-flow) that still assemble InfluxQL
    directly. New code should use `build_filters` and let the adapter render.
    """
    filters, applied, matched = build_filters(measurement, location, tags)
    clauses: list[str] = []
    for flt in filters:
        if len(flt.values) == 1:
            clauses.append(f"{ql.identifier(flt.key)} = {ql.literal(flt.values[0])}")
        else:
            joined = " OR ".join(
                f"{ql.identifier(flt.key)} = {ql.literal(v)}" for v in flt.values
            )
            clauses.append(f"({joined})")
    return clauses, applied, matched


def to_time_window(
    days: float | None = None,
    start: str | None = None,
    end: str | None = None,
) -> TimeWindow:
    """A structured `TimeWindow` from the three ways callers say "when".

    Mirrors `influxql.window`'s precedence (an exact start/end beats a rolling
    `days`, which beats all-of-history), but returns an adapter-neutral object
    rather than InfluxQL clauses. The minute count for a rolling window matches
    `influxql.window` exactly so both render the same query.
    """
    if start or end:
        return TimeWindow("absolute", start=start, end=end)
    if days is None:
        return TimeWindow("all")
    minutes = max(1, int(float(days) * 1440))
    return TimeWindow("relative", minutes=minutes)


def _checked_field(measurement: str, field: str | None) -> str:
    """The field to read, refusing one this measurement does not have.

    A field that does not exist produces perfectly valid InfluxQL over a
    column of nothing, so the query succeeds and returns an empty result. The
    caller then cannot tell "this sensor recorded nothing in that window" from
    "you asked for a field that has never existed" — and those need opposite
    responses. The first is an answer. The second is a typo.

    It is a live hazard rather than a theoretical one: `Water` keeps its
    readings in `litres` and `water_height`, and a model that guesses `value`
    gets an empty result that reads exactly like a dry tank.

    So an unknown field is refused, and the refusal names the real ones. The
    registry hands that text back to the model, which can correct itself on
    the next round instead of reporting an outage.
    """
    if not field:
        return default_field(measurement)

    available = [f["field"] for f in field_keys(measurement)]
    if field in available:
        return field

    raise QueryError(
        f"{measurement} has no field called {field!r}. Its fields are: "
        f"{', '.join(available) or '(none)'}. "
        f"Omit `field` to read {default_field(measurement)!r}, or call "
        f"describe({measurement!r}) to see the full schema."
    )


def prepare_query(
    measurement: str,
    field: str | None,
    location: str | None,
    tags: dict | None,
    phase: str | None = None,
) -> tuple[str, list[TagFilter], dict, list[str], str, str]:
    """Common setup: resolve the field, build structured filters, find the unit.

    Database-neutral. Returns
    (field, filters, applied_tags, matched_values, unit, unit_source).
    """
    tags = dict(tags or {})
    if phase is not None:
        tags["Phase"] = str(phase)

    field = _checked_field(measurement, field)
    filters, applied, matched = build_filters(measurement, location, tags)
    unit, unit_source = unit_for(measurement, field)
    return field, filters, applied, matched, unit, unit_source


def prepare(
    measurement: str,
    field: str | None,
    location: str | None,
    tags: dict | None,
    phase: str | None = None,
) -> tuple[str, list[str], dict, list[str], str, str]:
    """Like `prepare_query`, but returning InfluxQL clause strings.

    Kept for the advanced analyses (tank-flow) that still build InfluxQL
    directly. Returns (field, clauses, applied_tags, matched_values, unit,
    unit_source).
    """
    tags = dict(tags or {})
    if phase is not None:
        tags["Phase"] = str(phase)

    field = _checked_field(measurement, field)
    clauses, applied, matched = build_where(measurement, location, tags)
    unit, unit_source = unit_for(measurement, field)
    return field, clauses, applied, matched, unit, unit_source


def envelope(
    measurement: str,
    field: str,
    applied: dict,
    matched: list[str],
    unit: str,
    unit_source: str,
    query: str,
) -> dict[str, Any]:
    """The shape every tool result shares.

    `data` starts as None on purpose: a helper that finds nothing returns an
    explicit absence rather than a value, so there is nothing to fabricate an
    answer from.
    """
    out: dict[str, Any] = {
        "query": query,
        "measurement": measurement,
        "field": field,
        "tags": applied,
        "unit": unit,
        "unit_source": unit_source,
        "data": None,
    }
    if len(matched) > 1:
        out["matched_tag_values"] = matched
        out["note"] = (
            "This location exists under multiple capitalisations; all were "
            "included. Say so when reporting."
        )
    return out
