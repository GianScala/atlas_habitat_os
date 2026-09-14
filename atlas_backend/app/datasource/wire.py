"""InfluxDB 1.x wire helpers — shared by every InfluxQL-speaking adapter.

These are transport-agnostic: read-only enforcement and the flattening of an
InfluxDB `/query` response into ATLAS's boring series dict. Both the Grafana
proxy adapter and the direct-InfluxDB adapter reuse them, so the rule that
ATLAS never writes is defined once, in code, rather than per adapter.

The parsed shape every adapter returns:

    {"query": str, "database": str, "series": [
        {"name", "tags": {...}, "columns": [...], "values": [[...], ...]}
    ]}
"""

import re

from app.core.errors import DatasourceError


def assert_read_only(query: str) -> None:
    """Reject writes, multiple statements and comments before transport.

    Database credentials must independently enforce read-only access.
    """
    if (
        not re.match(r"^\s*(SELECT|SHOW)\b", query, re.IGNORECASE)
        or re.search(r"\bINTO\b", query, re.IGNORECASE)
        or any(token in query for token in (";", "--", "/*", "*/"))
    ):
        raise DatasourceError("Refusing query: only single read-only SELECT/SHOW allowed.")


def parse_influx_response(payload: dict, query: str, database: str) -> dict:
    """Flatten an InfluxDB 1.x /query response into a boring dict.

    In:  {"results": [{"series": [{"name","tags","columns","values"}]}]}
    Out: {"query", "database", "series": [...]}
    """
    results = payload.get("results") or []
    if results and results[0].get("error"):
        raise DatasourceError(
            f"InfluxDB rejected the query: {results[0]['error']} — query was: {query}"
        )

    series: list[dict] = []
    for result in results:
        for entry in result.get("series") or []:
            series.append(
                {
                    "name": entry.get("name"),
                    "tags": entry.get("tags") or {},
                    "columns": entry.get("columns") or [],
                    "values": entry.get("values") or [],
                }
            )

    return {"query": query, "database": database, "series": series}
