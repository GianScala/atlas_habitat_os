"""Point-in-time readings and short-term history.

Every function returns the exact query it ran and returns data=None when
InfluxDB gave back nothing. Nothing here invents, estimates, or interpolates
a value.
"""


from app.datasource import get_data_source
from app.datasource.query import GroupBy, Query, Select, TimeWindow
from app.telemetry import influxql as ql
from app.telemetry.filters import envelope, prepare_query
from app.telemetry.units import NON_SUMMABLE_FIELDS, unit_for


def get_latest(
    measurement: str,
    location: str | None = None,
    field: str | None = None,
    phase: str | None = None,
    tags: dict | None = None,
) -> dict:
    """The most recent reading: value, unit, and the instant it was taken.

    Reads ORDER BY time DESC LIMIT 1 rather than a last() aggregate, so the
    returned timestamp is unambiguously the timestamp of that actual point.
    """
    field, filters, applied, matched, unit, source = prepare_query(
        measurement, field, location, tags, phase
    )
    query = Query(
        measurement=measurement,
        selects=(Select(field),),
        filters=tuple(filters),
        order_desc=True,
        limit=1,
    )

    result = get_data_source().run(query)
    out = envelope(measurement, field, applied, matched, unit, source, result["query"])

    for _, columns, values in ql.rows(result):
        if not values:
            continue
        record = dict(zip(columns, values[0], strict=False))
        if record.get(field) is None:
            continue
        out["data"] = {"value": record[field], "time": record.get("time")}
        return out

    return out  # genuinely no data — the caller must say so, not guess


def get_history(
    measurement: str,
    location: str | None = None,
    field: str | None = None,
    minutes: int = 60,
    phase: str | None = None,
    tags: dict | None = None,
) -> dict:
    """Time-bucketed mean over the last N minutes, for short-term trends."""
    field, filters, applied, matched, unit, source = prepare_query(
        measurement, field, location, tags, phase
    )
    minutes = max(1, int(minutes))
    bucket = max(1, minutes // 12)

    query = Query(
        measurement=measurement,
        selects=(Select(field, "mean"),),
        filters=tuple(filters),
        window=TimeWindow("relative", minutes=minutes),
        group_by=GroupBy(bucket_minutes=bucket, fill_none=True),
    )

    result = get_data_source().run(query)
    out = envelope(measurement, field, applied, matched, unit, source, result["query"])
    out.update({"minutes": minutes, "bucket_minutes": bucket})

    points = [
        {"time": record.get("time"), "value": record["mean"]}
        for _, columns, values in ql.rows(result)
        for record in ql.records(columns, values)
        if record.get("mean") is not None
    ]
    if points:
        out["data"] = points
        out["count"] = len(points)
    return out


def time_range(
    measurement: str,
    field: str | None = None,
    location: str | None = None,
    tags: dict | None = None,
) -> dict:
    """The timestamps of the OLDEST and NEWEST readings on record.

    Call this before choosing a time window, so a window is picked from what
    the data actually covers rather than assumed — and before calling anything
    an all-time high.
    """
    field, filters, applied, matched, unit, source = prepare_query(
        measurement, field, location, tags, None
    )
    source_ds = get_data_source()

    def endpoint(descending: bool) -> tuple[dict | None, str]:
        query = Query(
            measurement=measurement,
            selects=(Select(field),),
            filters=tuple(filters),
            order_desc=descending,
            limit=1,
        )
        result = source_ds.run(query)
        for _, columns, values in ql.rows(result):
            if values:
                record = dict(zip(columns, values[0], strict=False))
                return {"time": record.get("time"), "value": record.get(field)}, result["query"]
        return None, result["query"]

    oldest, oldest_query = endpoint(descending=False)
    newest, newest_query = endpoint(descending=True)

    out = envelope(measurement, field, applied, matched, unit, source, oldest_query)
    out["queries"] = [oldest_query, newest_query]
    if oldest and newest:
        out["data"] = {"oldest": oldest, "newest": newest}
    return out


def get_latest_all_phases(field: str | None = None) -> dict:
    """Every electrical phase's latest reading, for total-draw questions.

    Which measurement holds the phased meter, what its phase tag is called, and
    which phases exist are habitat-specific, so they come from the habitat
    profile's `electrical:` section rather than being hardcoded. Returns each
    phase separately AND their sum; a missing phase is listed in `missing_phases`
    and excluded, never assumed to be zero.
    """
    from app.habitat import profile

    electrical = profile().electrical
    measurement = electrical.get("measurement", "Electricity")
    phase_tag = electrical.get("phase_tag", "Phase")
    phases = [str(p) for p in electrical.get("phases", ["1", "2", "3"])]
    field = field or electrical.get("default_field", "current")

    per_phase: list[dict] = []
    missing: list[str] = []
    queries: list[str] = []

    for phase in phases:
        reading = get_latest(measurement, field=field, tags={phase_tag: phase})
        queries.append(reading["query"])
        if reading["data"] is None:
            missing.append(phase)
        else:
            per_phase.append(
                {
                    "phase": phase,
                    "value": reading["data"]["value"],
                    "time": reading["data"]["time"],
                }
            )

    unit, source = unit_for(measurement, field)
    out: dict = {
        "queries": queries,
        "measurement": measurement,
        "field": field,
        "unit": unit,
        "unit_source": source,
        "missing_phases": missing,
        "data": None,
    }

    if field in NON_SUMMABLE_FIELDS:
        out["warning"] = (
            f"Summing {field} across phases is not physically meaningful. "
            "Report the per-phase values instead of the sum."
        )

    if per_phase:
        out["data"] = {
            "phases": per_phase,
            "sum": round(sum(p["value"] for p in per_phase), 3),
            "phases_included": [p["phase"] for p in per_phase],
        }
    return out
