"""Shape flat (location, time, value) rows into InfluxDB-style series.

Any adapter that can fetch matching readings as rows — the SQLite adapter, the
SQL mapping adapter, a CSV reader — turns them into the series shape the
telemetry layer reads by calling `shape_rows`. Bucketing and aggregation happen
here, in Python, so an adapter only has to fetch and hand over rows.

This is what lets a non-InfluxQL store answer a structured `Query`: the query's
selects, grouping, and time bucket are applied uniformly whatever the backend.
"""

from collections.abc import Iterable
from datetime import UTC, datetime

from app.core.errors import DatasourceError
from app.datasource.query import GroupBy, Query

# A fetched reading: (location or None, epoch seconds UTC, numeric value).
Row = tuple[str | None, float, float]


def iso(epoch: float) -> str:
    """Epoch seconds -> the RFC3339/UTC string InfluxDB would have returned."""
    return datetime.fromtimestamp(epoch, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _bucket_shift(gb: GroupBy) -> int:
    """Seconds to shift bucket boundaries off UTC midnight (mirrors InfluxQL).

    InfluxQL's `GROUP BY time(d, offset)` moves each boundary forward; the
    render layer passes the same habitat-ahead figure and computes the shift the
    same way, so buckets line up across every backend.
    """
    period_min = gb.bucket_minutes or 1
    shift_min = int(-gb.offset_minutes) % period_min
    return shift_min * 60


def _bucket_start(ts: float, period_seconds: int, shift_seconds: int) -> float:
    return ((ts - shift_seconds) // period_seconds) * period_seconds + shift_seconds


def _aggregate(fn: str, ordered_values: list) -> float | None:
    """Apply one aggregate. `ordered_values` are in ascending-time order."""
    if not ordered_values:
        return None
    if fn == "mean":
        return sum(ordered_values) / len(ordered_values)
    if fn == "min":
        return min(ordered_values)
    if fn == "max":
        return max(ordered_values)
    if fn == "sum":
        return sum(ordered_values)
    if fn == "count":
        return len(ordered_values)
    if fn == "first":
        return ordered_values[0]
    if fn == "last":
        return ordered_values[-1]
    raise DatasourceError(f"Cannot compute aggregate {fn!r} in-process.")


def shape_rows(
    query: Query, field: str, rows: Iterable[Row], location_key: str
) -> list[dict]:
    """Turn flat rows into InfluxDB-shaped series the analysis already reads.

    `rows` must be ordered by ascending time so first()/last() are correct.
    """
    rows = list(rows)
    gb = query.group_by

    # Raw point read (get_latest / time_range): one series, columns time+field.
    if not query.selects[0].fn:
        values = [[iso(ts), value] for _loc, ts, value in rows]
        return [
            {
                "name": query.measurement,
                "tags": {},
                "columns": ["time", field],
                "values": values,
            }
        ]

    group_by_location = bool(gb and (gb.all_tags or location_key in gb.tags))
    bucket_seconds = (gb.bucket_minutes * 60) if (gb and gb.bucket_minutes) else None
    shift_seconds = _bucket_shift(gb) if bucket_seconds else 0

    # (location|None) -> (bucket_start|None) -> [values in time order]
    grouped: dict = {}
    for loc, ts, value in rows:
        key_loc = loc if group_by_location else None
        bucket = (
            _bucket_start(ts, bucket_seconds, shift_seconds) if bucket_seconds else None
        )
        grouped.setdefault(key_loc, {}).setdefault(bucket, []).append(value)

    columns = ["time", *(s.alias for s in query.selects)]
    series: list[dict] = []
    for loc in sorted(grouped, key=lambda x: (x is not None, x)):
        tags = {location_key: loc} if (group_by_location and loc is not None) else {}
        values = []
        for bucket in sorted(grouped[loc], key=lambda x: (x is not None, x)):
            nums = grouped[loc][bucket]
            row = [iso(bucket) if bucket is not None else None]
            row.extend(_aggregate(s.fn, nums) for s in query.selects)
            values.append(row)
        series.append(
            {"name": query.measurement, "tags": tags, "columns": columns, "values": values}
        )
    return series
