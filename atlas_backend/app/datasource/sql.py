"""SQL adapter — map ATLAS onto an existing relational habitat database.

The adapter that answers your "PostgreSQL / MySQL / TimescaleDB" question. It
connects to any SQL database over a DSN and reads a table whose columns you
DESCRIBE in the habitat profile — you do not reshape your data to fit ATLAS,
you tell ATLAS how your data is shaped:

    # in the habitat profile (HABITAT_CONFIG)
    sql_mapping:
      table: sensor_readings
      measurement_column: metric_type   # e.g. "temperature"
      location_column: room             # optional (the place); omit if none
      field_column: null                # optional; omit -> every row is "value"
      time_column: ts
      value_column: value
      time_encoding: epoch              # epoch | iso | datetime

    # in .env
    DATA_SOURCE=sql
    SQL_DSN=postgresql://user:pass@host:5432/habitat

So a table like `sensor_readings(sensor_id, room, metric_type, ts, value)` is
served with no schema migration — the adapter builds a portable `SELECT` from
the mapping, fetches the matching rows, and aggregates them with the shared
`rowagg` helpers (the same code the SQLite adapter uses).

## Drivers

Connections use Python's stdlib DB-API, so no heavyweight ORM is pulled in:

    sqlite:///path/to.db          -> stdlib sqlite3 (also how this is tested)
    postgresql://…  /  postgres://…  -> psycopg (v3) or psycopg2   [pip install]
    mysql://…                     -> pymysql                        [pip install]

The Postgres/MySQL drivers are optional installs the deploying mission adds; a
missing one produces a clear message naming the package to install.

## Scope (v1)

Aggregation happens in-process after fetching the matching rows — correct and
portable across every SQL dialect, and fine at habitat scale. A connection is
opened per query. Pushing aggregates into SQL and pooling connections are later
optimisations; correctness does not depend on them.
"""

import importlib
import re
import time
from datetime import UTC, datetime

from app.config import get_settings
from app.core.errors import ConfigurationError, DatasourceError
from app.datasource.base import CAP_QUERY, DataSource
from app.datasource.query import Query, TimeWindow
from app.datasource.rowagg import shape_rows
from app.habitat import profile

_SAFE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _ident(name: str) -> str:
    """Quote a table/column name after refusing anything but a plain identifier.

    These come from the habitat profile, not the model, but a typo should fail
    loudly rather than open an injection path.
    """
    if not isinstance(name, str) or not _SAFE_IDENT.match(name):
        raise ConfigurationError(f"Unsafe SQL identifier in sql_mapping: {name!r}")
    return f'"{name}"'


class _Mapping:
    """The habitat's table layout, from the profile's `sql_mapping` section."""

    def __init__(self, raw: dict):
        if not raw or not raw.get("table"):
            raise ConfigurationError(
                "DATA_SOURCE=sql needs a `sql_mapping` section (with at least "
                "`table`, `measurement_column`, `time_column`, `value_column`) "
                "in the habitat profile."
            )
        self.table = str(raw["table"])
        self.measurement = str(raw.get("measurement_column") or "measurement")
        self.time = str(raw.get("time_column") or "ts")
        self.value = str(raw.get("value_column") or "value")
        self.location = raw.get("location_column") or None
        self.field = raw.get("field_column") or None
        self.time_encoding = str(raw.get("time_encoding") or "epoch").lower()
        if self.time_encoding not in ("epoch", "iso", "datetime"):
            raise ConfigurationError(
                f"sql_mapping.time_encoding must be epoch | iso | datetime, "
                f"got {self.time_encoding!r}."
            )


def _mapping() -> _Mapping:
    return _Mapping(profile().sql_mapping)


def _location_key() -> str:
    keys = profile().location_tag_keys
    return keys[0] if keys else "Location"


# --------------------------------------------------------------------------
# DB-API connection, chosen from the DSN scheme
# --------------------------------------------------------------------------


def _connect():
    """(connection, placeholder) for the configured DSN. Placeholder is '?' or '%s'."""
    dsn = get_settings().sql_dsn
    if not dsn:
        raise ConfigurationError("SQL_DSN is not set. Fill it in, or change DATA_SOURCE.")
    scheme = dsn.split("://", 1)[0].lower()

    if scheme == "sqlite":
        import sqlite3

        # sqlite:///relative.db (relative) | sqlite:////abs.db (absolute).
        remainder = dsn.split("://", 1)[1]
        path = remainder[1:] if remainder.startswith("/") else remainder
        from pathlib import Path

        return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True), "?"

    if scheme in ("postgresql", "postgres"):
        module = _first_driver(["psycopg", "psycopg2"], "PostgreSQL",
                               "pip install 'psycopg[binary]'  (or psycopg2-binary)")
        timeout = get_settings().datasource_timeout
        return module.connect(
            dsn, connect_timeout=timeout,
            options=(
                "-c default_transaction_read_only=on "
                f"-c statement_timeout={timeout * 1000}"
            ),
        ), "%s"

    if scheme == "mysql":
        module = _first_driver(["pymysql"], "MySQL", "pip install pymysql")
        # pymysql wants host/user/... rather than a URL; parse the DSN.
        return module.connect(**_mysql_params(dsn)), "%s"

    raise ConfigurationError(
        f"Unsupported SQL_DSN scheme {scheme!r}. Use sqlite, postgresql, or mysql."
    )


def _first_driver(candidates: list[str], name: str, hint: str):
    for mod in candidates:
        try:
            return importlib.import_module(mod)
        except ImportError:
            continue
    raise ConfigurationError(
        f"No {name} driver installed. Tried {', '.join(candidates)}. {hint}"
    )


def _mysql_params(dsn: str) -> dict:
    from urllib.parse import unquote, urlparse

    u = urlparse(dsn)
    return {
        "host": u.hostname or "localhost",
        "port": u.port or 3306,
        "user": unquote(u.username or ""),
        "password": unquote(u.password or ""),
        "database": (u.path or "/").lstrip("/"),
        "connect_timeout": get_settings().datasource_timeout,
        "read_timeout": get_settings().datasource_timeout,
        "write_timeout": get_settings().datasource_timeout,
        "sql_mode": "ANSI_QUOTES",
        "init_command": "SET SESSION TRANSACTION READ ONLY",
    }


# --------------------------------------------------------------------------
# Time helpers
# --------------------------------------------------------------------------


def _to_epoch(value, encoding: str) -> float:
    if encoding == "epoch":
        return float(value)
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=UTC)
        return moment.timestamp()
    text = str(value).strip().replace("Z", "+00:00").replace(" ", "T", 1)
    try:
        moment = datetime.fromisoformat(text)
    except ValueError as exc:
        raise DatasourceError(f"Unparseable time value {value!r} from SQL.") from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.timestamp()


def _epoch_bounds(win: TimeWindow) -> tuple[float | None, float | None]:
    """(low, high) epoch bounds for a window, for the in-process safety filter."""
    if win.kind == "relative":
        return time.time() - win.minutes * 60, None
    if win.kind == "absolute":
        lo = _iso_to_epoch(win.start) if win.start else None
        hi = _iso_to_epoch(win.end) if win.end else None
        return lo, hi
    return None, None


def _iso_to_epoch(text: str) -> float:
    t = str(text).strip().replace("Z", "+00:00")
    moment = datetime.fromisoformat(t)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.timestamp()


def _bound_literal(epoch: float, encoding: str):
    """A window bound in the column's own type, for pushing into SQL."""
    if encoding == "epoch":
        return epoch
    moment = datetime.fromtimestamp(epoch, tz=UTC)
    if encoding == "datetime":
        return moment.replace(tzinfo=None)  # naive UTC, what most columns store
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")  # iso


# --------------------------------------------------------------------------
# The adapter
# --------------------------------------------------------------------------


class SqlDataSource(DataSource):
    """Reach a habitat whose telemetry lives in a mapped SQL table."""

    label = "SQL"
    capabilities = frozenset({CAP_QUERY})  # no raw InfluxQL

    def configured(self) -> bool:
        return bool(get_settings().sql_dsn and profile().sql_mapping.get("table"))

    def describe(self) -> str:
        dsn = get_settings().sql_dsn or "(unset)"
        table = profile().sql_mapping.get("table", "?")
        return f"SQL at {dsn.split('://', 1)[0]}://… table {table}"

    # --- helpers ----------------------------------------------------------

    def _query_rows(self, sql: str, params: list) -> list:
        conn, placeholder = _connect()
        if placeholder != "?":
            sql = sql.replace("?", placeholder)
        try:
            cur = conn.cursor()
            cur.execute(sql, params)
            return cur.fetchall()
        except Exception as exc:  # driver-specific errors -> one plain reason
            raise DatasourceError(f"SQL query failed: {exc}") from exc
        finally:
            conn.close()

    # --- discovery --------------------------------------------------------

    def measurements(self) -> list[str]:
        m = _mapping()
        rows = self._query_rows(
            f"SELECT DISTINCT {_ident(m.measurement)} FROM {_ident(m.table)}", []
        )
        return sorted(str(r[0]) for r in rows if r[0] is not None)

    def field_keys(self, measurement: str) -> list[dict]:
        m = _mapping()
        if not m.field:
            return [{"field": "value", "type": "float"}]
        rows = self._query_rows(
            f"SELECT DISTINCT {_ident(m.field)} FROM {_ident(m.table)} "
            f"WHERE {_ident(m.measurement)} = ?",
            [measurement],
        )
        return [{"field": str(r[0]), "type": "float"} for r in rows if r[0] is not None]

    def tag_keys(self, measurement: str) -> list[str]:
        m = _mapping()
        if not m.location:
            return []
        rows = self._query_rows(
            f"SELECT 1 FROM {_ident(m.table)} WHERE {_ident(m.measurement)} = ? "
            f"AND {_ident(m.location)} IS NOT NULL LIMIT 1",
            [measurement],
        )
        return [_location_key()] if rows else []

    def tag_values(self, measurement: str, tag_key: str) -> list[str]:
        m = _mapping()
        if not m.location or tag_key != _location_key():
            return []
        rows = self._query_rows(
            f"SELECT DISTINCT {_ident(m.location)} FROM {_ident(m.table)} "
            f"WHERE {_ident(m.measurement)} = ? AND {_ident(m.location)} IS NOT NULL",
            [measurement],
        )
        return sorted(str(r[0]) for r in rows if r[0] is not None)

    def schema_index(self) -> dict[str, dict[str, list[str]]]:
        m = _mapping()
        key = _location_key()
        index: dict[str, dict[str, list[str]]] = {}
        select = [_ident(m.measurement)]
        if m.field:
            select.append(_ident(m.field))
        if m.location:
            select.append(_ident(m.location))
        rows = self._query_rows(
            f"SELECT DISTINCT {', '.join(select)} FROM {_ident(m.table)}", []
        )
        for r in rows:
            name = str(r[0])
            entry = index.setdefault(name, {"fields": [], "tags": []})
            col = 1
            if m.field and r[col] is not None and str(r[col]) not in entry["fields"]:
                entry["fields"].append(str(r[col]))
            if m.field:
                col += 1
            if m.location and r[col] is not None and key not in entry["tags"]:
                entry["tags"].append(key)
        if not m.field:
            for entry in index.values():
                entry["fields"] = ["value"]
        return index

    # --- the structured query path ----------------------------------------

    def run(self, query: Query) -> dict:
        m = _mapping()
        field = query.selects[0].field

        select = f"{_ident(m.time)}, "
        select += f"{_ident(m.location)}" if m.location else "NULL"
        select += f", {_ident(m.value)}"

        where = [f"{_ident(m.measurement)} = ?"]
        params: list = [query.measurement]
        if m.field:
            where.append(f"{_ident(m.field)} = ?")
            params.append(field)

        loc_key = _location_key()
        if m.location:
            for flt in query.filters:
                if flt.key == loc_key:
                    where.append(
                        f"{_ident(m.location)} IN ({', '.join('?' for _ in flt.values)})"
                    )
                    params.extend(flt.values)

        # Point reads (get_latest / time_range) carry no window but an
        # ORDER BY + LIMIT, so those push into SQL. Aggregate queries carry a
        # window and no limit; we push a best-effort time bound and then filter
        # exactly in Python, so correctness never rests on SQL time semantics.
        lo, hi = _epoch_bounds(query.window)
        if query.limit is None:
            if lo is not None:
                where.append(f"{_ident(m.time)} >= ?")
                params.append(_bound_literal(lo, m.time_encoding))
            if hi is not None:
                where.append(f"{_ident(m.time)} <= ?")
                params.append(_bound_literal(hi, m.time_encoding))

        sql = f"SELECT {select} FROM {_ident(m.table)} WHERE {' AND '.join(where)}"
        if query.order_desc is not None:
            sql += " ORDER BY " + _ident(m.time) + (" DESC" if query.order_desc else " ASC")
        else:
            sql += " ORDER BY " + _ident(m.time) + " ASC"
        if query.limit is not None:
            sql += f" LIMIT {int(query.limit)}"

        raw_rows = self._query_rows(sql, params)

        flat = []
        for t, loc, value in raw_rows:
            if value is None:
                continue
            epoch = _to_epoch(t, m.time_encoding)
            if query.limit is None:
                if lo is not None and epoch < lo:
                    continue
                if hi is not None and epoch > hi:
                    continue
            flat.append((str(loc) if loc is not None else None, epoch, float(value)))

        series = shape_rows(query, field, flat, loc_key)
        human = f"sql: {field} of {query.measurement}"
        return {"query": human, "database": m.table, "series": series}
