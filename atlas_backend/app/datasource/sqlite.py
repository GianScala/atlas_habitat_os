"""SQLite adapter — a habitat backed by a local SQLite file, no InfluxDB.

This is the proof that ATLAS is database-agnostic: it implements the same
structured `DataSource` interface as the InfluxQL adapters, but answers from a
plain SQLite file and never speaks InfluxQL. Point at one with:

    DATA_SOURCE=sqlite
    SQLITE_PATH=config/examples/demo_habitat.db

## Canonical schema

The adapter reads one long/narrow table — the universal shape of habitat
time-series, which any store (SQLite, Postgres, a CSV import) can be mapped to:

    CREATE TABLE readings (
        measurement TEXT NOT NULL,   -- e.g. "Temperature"
        location    TEXT,            -- the place tag value, or NULL
        field       TEXT NOT NULL,   -- e.g. "value"
        ts          REAL NOT NULL,   -- Unix epoch seconds, UTC
        value       REAL NOT NULL
    );

`location` is reported under the habitat profile's first location tag key (e.g.
"Location"), so discovery, zone naming, and per-place queries all work exactly
as they do on InfluxDB. Aggregation is done in-process after fetching the
matching rows — correct and simple at the local scale this adapter is for.

Advanced analyses expressed as raw InfluxQL (tank-flow, the charting
time-series) are not offered on this adapter; the tool registry gates them on
the `raw_influxql` capability, which this adapter does not advertise.
"""

import sqlite3
import time
from datetime import UTC, datetime

from app.config import get_settings
from app.core.errors import ConfigurationError, DatasourceError
from app.datasource.base import CAP_QUERY, DataSource
from app.datasource.query import Query
from app.datasource.rowagg import shape_rows
from app.habitat import profile

_SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    measurement TEXT NOT NULL,
    location    TEXT,
    field       TEXT NOT NULL,
    ts          REAL NOT NULL,
    value       REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_readings_lookup
    ON readings (measurement, field, ts);
"""


def _iso(epoch: float) -> str:
    """Epoch seconds -> the RFC3339/UTC string InfluxDB would have returned."""
    return datetime.fromtimestamp(epoch, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _location_key() -> str:
    """The tag key name this adapter reports its `location` column under."""
    keys = profile().location_tag_keys
    return keys[0] if keys else "Location"


class SqliteDataSource(DataSource):
    """Reach a habitat whose telemetry lives in a local SQLite file."""

    label = "SQLite"
    capabilities = frozenset({CAP_QUERY})  # no raw InfluxQL

    def _connect(self) -> sqlite3.Connection:
        path = get_settings().resolved_sqlite_path
        if not path.exists():
            raise ConfigurationError(
                f"SQLite habitat file not found at {path}. Set SQLITE_PATH, or "
                "build the demo with scripts/seed_demo_sqlite.py."
            )
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def configured(self) -> bool:
        return get_settings().resolved_sqlite_path.exists()

    def describe(self) -> str:
        return f"SQLite at {get_settings().resolved_sqlite_path}"

    # --- discovery --------------------------------------------------------

    def measurements(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT measurement FROM readings ORDER BY measurement"
            ).fetchall()
        return [r["measurement"] for r in rows]

    def field_keys(self, measurement: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT field FROM readings WHERE measurement = ? "
                "ORDER BY field",
                (measurement,),
            ).fetchall()
        return [{"field": r["field"], "type": "float"} for r in rows]

    def tag_keys(self, measurement: str) -> list[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM readings WHERE measurement = ? AND location IS NOT NULL "
                "LIMIT 1",
                (measurement,),
            ).fetchone()
        return [_location_key()] if row else []

    def tag_values(self, measurement: str, tag_key: str) -> list[str]:
        if tag_key != _location_key():
            return []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT location FROM readings WHERE measurement = ? "
                "AND location IS NOT NULL ORDER BY location",
                (measurement,),
            ).fetchall()
        return [r["location"] for r in rows]

    def schema_index(self) -> dict[str, dict[str, list[str]]]:
        key = _location_key()
        index: dict[str, dict[str, list[str]]] = {}
        with self._connect() as conn:
            for r in conn.execute(
                "SELECT DISTINCT measurement, field FROM readings"
            ).fetchall():
                index.setdefault(r["measurement"], {"fields": [], "tags": []})[
                    "fields"
                ].append(r["field"])
            for r in conn.execute(
                "SELECT DISTINCT measurement FROM readings WHERE location IS NOT NULL"
            ).fetchall():
                index.setdefault(r["measurement"], {"fields": [], "tags": []})[
                    "tags"
                ].append(key)
        return index

    # --- the structured query path ----------------------------------------

    def run(self, query: Query) -> dict:
        field = query.selects[0].field
        sql, params, human = self._to_sql(query, field)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        flat = [(r["location"], float(r["ts"]), r["value"]) for r in rows]
        series = shape_rows(query, field, flat, _location_key())
        return {
            "query": human,
            "database": get_settings().resolved_sqlite_path.name,
            "series": series,
        }

    def _to_sql(self, query: Query, field: str) -> tuple[str, list, str]:
        """SQL fetching the matching raw rows, ordered by time.

        Bucketing and aggregation happen in `_shape`, so this stays a plain,
        correct row fetch whatever the aggregate.
        """
        where = ["measurement = ?", "field = ?"]
        params: list = [query.measurement, field]

        loc_key = _location_key()
        for flt in query.filters:
            if flt.key == loc_key:
                placeholders = ", ".join("?" for _ in flt.values)
                where.append(f"location IN ({placeholders})")
                params.extend(flt.values)
            # Non-location tags are not part of the canonical schema; ignored.

        win = query.window
        if win.kind == "relative":
            where.append("ts > ?")
            params.append(time.time() - win.minutes * 60)
        elif win.kind == "absolute":
            if win.start:
                where.append("ts >= ?")
                params.append(_epoch(win.start))
            if win.end:
                where.append("ts <= ?")
                params.append(_epoch(win.end))

        order = ""
        if query.order_desc is not None:
            order = " ORDER BY ts DESC" if query.order_desc else " ORDER BY ts ASC"
        else:
            order = " ORDER BY ts ASC"
        limit = f" LIMIT {int(query.limit)}" if query.limit is not None else ""

        sql = (
            "SELECT location, ts, value FROM readings WHERE "
            + " AND ".join(where)
            + order
            + limit
        )
        human = f"sqlite: {field} of {query.measurement}" + (
            f" (last {win.minutes}m)" if win.kind == "relative" else ""
        )
        return sql, params, human


def _epoch(value: str) -> float:
    text = str(value).strip().replace("Z", "+00:00")
    try:
        moment = datetime.fromisoformat(text)
    except ValueError as exc:
        raise DatasourceError(f"Not an ISO 8601 timestamp: {value!r}") from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.timestamp()
