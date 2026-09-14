"""Habitat telemetry: discovery, readings, and aggregation over InfluxDB.

The transport — how a query actually reaches the database — lives one layer
below this package, in `app.datasource`, behind the `influxql()` function. This
package builds InfluxQL and parses series; it does not know or care whether a
Grafana proxy or a direct InfluxDB connection answers.

Layering, innermost first:

    (app.datasource) transport. The only place that knows Grafana/InfluxDB.
    influxql.py     pure string construction and parsing. No schema knowledge.
    units.py        the one thing that cannot be discovered.
    zones.py        human names for tag values; internal-metric prefixes.
    discovery.py    the database describing itself, cached per process.
    filters.py      question terms -> WHERE clauses; the result envelope.
    readings.py     point-in-time values and short-term history.
    aggregation.py  statistics and consumption over long windows.
    availability.py what is live right now, as opposed to what exists.

Nothing in this package knows about Anthropic, HTTP, or the chat UI.
"""
