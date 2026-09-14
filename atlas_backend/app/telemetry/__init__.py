"""Habitat telemetry: discovery, readings, and aggregation.

The transport - how a query actually reaches the database - lives one layer
below this package, in `app.datasource`. This package builds a structured
`Query` and reads the series that come back; it does not know or care which
adapter answers, or what dialect that adapter speaks.

Layering, innermost first:

    (app.datasource) transport. The only place that knows a database product.
    influxql.py     time windows, bucketing, and row shaping, plus the
                    identifier/literal quoting the filter builder needs. Pure
                    functions, no schema knowledge. Named for its origin; the
                    helpers the rest of this package uses are dialect-neutral.
    units.py        the one thing that cannot be discovered.
    zones.py        human names for tag values; internal-metric prefixes.
    discovery.py    the database describing itself, cached per process.
    filters.py      question terms -> WHERE clauses; the result envelope.
    readings.py     point-in-time values and short-term history.
    aggregation.py  statistics and consumption over long windows.
    availability.py what is live right now, as opposed to what exists.

Nothing in this package knows about Anthropic, HTTP, or the chat UI.
"""
