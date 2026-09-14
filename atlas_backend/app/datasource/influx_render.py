"""Render a structured `Query` into an InfluxQL string.

The InfluxQL dialect half of the InfluxQL adapters. It reuses the pure,
schema-free string helpers in `app.telemetry.influxql` (identifier quoting,
literal escaping, duration and time-bucket formatting), which also enforce that
model-chosen identifiers and timestamps are safe rather than escaped cleverly.

Column naming matches InfluxDB's own defaults on purpose: an aggregate column is
named after its function (`mean`, `first`, ...), a raw column after its field,
and every series carries an implicit leading `time`. The telemetry layer reads
results by those names, so the SQLite adapter aliases its columns identically.
"""

from app.datasource.query import Query
from app.telemetry import influxql as ql


def _select_list(query: Query) -> str:
    parts = []
    for sel in query.selects:
        ident = ql.identifier(sel.field)
        parts.append(f"{sel.fn}({ident})" if sel.fn else ident)
    return ", ".join(parts)


def _where(query: Query) -> str:
    clauses: list[str] = []

    for flt in query.filters:
        if len(flt.values) == 1:
            clauses.append(f"{ql.identifier(flt.key)} = {ql.literal(flt.values[0])}")
        else:
            joined = " OR ".join(
                f"{ql.identifier(flt.key)} = {ql.literal(v)}" for v in flt.values
            )
            clauses.append(f"({joined})")

    win = query.window
    if win.kind == "relative":
        clauses.append(f"time > now() - {ql.duration(win.minutes)}")
    elif win.kind == "absolute":
        if win.start:
            clauses.append(f"time >= {ql.timestamp(win.start)}")
        if win.end:
            clauses.append(f"time <= {ql.timestamp(win.end)}")

    return f" WHERE {' AND '.join(clauses)}" if clauses else ""


def _group_by(query: Query) -> str:
    gb = query.group_by
    if gb is None:
        return ""

    parts: list[str] = []
    if gb.bucket_minutes:
        parts.append(ql.time_group(gb.bucket_minutes, gb.offset_minutes))
    if gb.all_tags:
        parts.append("*")
    else:
        parts.extend(ql.identifier(t) for t in gb.tags)

    if not parts:
        return ""
    clause = f" GROUP BY {', '.join(parts)}"
    if gb.bucket_minutes and gb.fill_none:
        clause += " fill(none)"
    return clause


def _order_limit(query: Query) -> str:
    out = ""
    if query.order_desc is not None:
        out += " ORDER BY time DESC" if query.order_desc else " ORDER BY time ASC"
    if query.limit is not None:
        out += f" LIMIT {int(query.limit)}"
    return out


def render(query: Query) -> str:
    """The InfluxQL string for a structured Query."""
    return (
        f"SELECT {_select_list(query)} "
        f"FROM {ql.identifier(query.measurement)}"
        f"{_where(query)}{_group_by(query)}{_order_limit(query)}"
    )
