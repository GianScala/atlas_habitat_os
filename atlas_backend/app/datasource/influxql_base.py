"""Shared implementation for every InfluxQL-speaking adapter.

Grafana-proxy and direct-InfluxDB differ only in *transport* — how a query
string becomes raw InfluxDB JSON, and how the database name is resolved.
Everything else — read-only enforcement, response parsing, rendering a
structured `Query` to InfluxQL, and answering discovery through `SHOW` — is
identical, and lives here. A concrete adapter implements two methods:

    _fetch(query, database, uid) -> raw InfluxDB JSON
    _database(uid) -> the database name to query
"""

from abc import abstractmethod

from app.datasource.base import CAP_QUERY, CAP_RAW_INFLUXQL, DataSource
from app.datasource.influx_render import render
from app.datasource.query import Query
from app.datasource.wire import assert_read_only, parse_influx_response
from app.telemetry import influxql as ql


class InfluxQLDataSource(DataSource):
    """A DataSource backed by an InfluxDB 1.x database, spoken in InfluxQL."""

    capabilities = frozenset({CAP_QUERY, CAP_RAW_INFLUXQL})

    # --- transport, provided by the concrete adapter ----------------------

    @abstractmethod
    def _fetch(self, query: str, database: str, uid: str | None) -> dict:
        """Send an InfluxQL string and return InfluxDB's raw JSON payload."""

    @abstractmethod
    def _database(self, uid: str | None = None) -> str:
        """The InfluxDB database name to query."""

    # --- the query path, shared -------------------------------------------

    def _query(
        self, query: str, db: str | None = None, uid: str | None = None
    ) -> dict:
        assert_read_only(query)
        database = db or self._database(uid)
        payload = self._fetch(query, database, uid)
        return parse_influx_response(payload, query, database)

    def influxql(
        self, query: str, db: str | None = None, uid: str | None = None
    ) -> dict:
        return self._query(query, db=db, uid=uid)

    def run(self, query: Query) -> dict:
        return self._query(render(query))

    # --- discovery, via SHOW ----------------------------------------------

    def measurements(self) -> list[str]:
        result = self._query("SHOW MEASUREMENTS")
        return sorted(row[0] for s in result["series"] for row in s["values"] if row)

    def field_keys(self, measurement: str) -> list[dict]:
        result = self._query(f"SHOW FIELD KEYS FROM {ql.identifier(measurement)}")
        return [
            {"field": row[0], "type": row[1] if len(row) > 1 else ""}
            for s in result["series"]
            for row in s["values"]
            if row
        ]

    def tag_keys(self, measurement: str) -> list[str]:
        result = self._query(f"SHOW TAG KEYS FROM {ql.identifier(measurement)}")
        return [row[0] for s in result["series"] for row in s["values"] if row]

    def tag_values(self, measurement: str, tag_key: str) -> list[str]:
        result = self._query(
            f"SHOW TAG VALUES FROM {ql.identifier(measurement)} "
            f"WITH KEY = {ql.identifier(tag_key)}"
        )
        values = [row[-1] for s in result["series"] for row in s["values"] if row]
        return sorted(set(values))

    def schema_index(self) -> dict[str, dict[str, list[str]]] | None:
        """The whole schema in two round trips (SHOW ... KEYS without FROM).

        InfluxQL returns one series per measurement, so field and tag keys for
        every measurement cost two queries rather than two per measurement.
        Returns None (caller falls back per-measurement) if the server rejects
        the FROM-less form.
        """
        from app.core.errors import DatasourceError

        index: dict[str, dict[str, list[str]]] = {}

        def sweep(query: str, bucket: str) -> bool:
            try:
                result = self._query(query)
            except DatasourceError:
                return False
            for series in result["series"]:
                name = series.get("name")
                if not name:
                    continue
                entry = index.setdefault(name, {"fields": [], "tags": []})
                for row in series.get("values") or []:
                    if row:
                        entry[bucket].append(str(row[0]))
            return True

        ok_fields = sweep("SHOW FIELD KEYS", "fields")
        ok_tags = sweep("SHOW TAG KEYS", "tags")
        if not (ok_fields or ok_tags):
            return None
        return index
