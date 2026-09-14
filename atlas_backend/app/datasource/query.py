"""The structured query — ATLAS Core's database-neutral way to ask for data.

This is the seam that makes ATLAS database-agnostic. The telemetry layer builds
a `Query` describing *what* it wants — a measurement, a field, an aggregate, a
time window, a grouping — and hands it to the active `DataSource`. Each adapter
renders the same `Query` into its own dialect:

    Query  --InfluxQLDataSource-->  "SELECT mean(value) FROM ... GROUP BY time(1h)"
           --SqliteDataSource---->  "SELECT avg(value) FROM readings ... GROUP BY bucket"

and returns the same `Result` shape, so nothing above the adapter — the analysis,
the unit captioning, the provenance footer — knows or cares which database
answered.

The model deliberately covers exactly the query shapes ATLAS's telemetry
actually issues, no more: point reads, bucketed aggregates, and raw histories.
It is not a general query language, and it is not meant to become one.
"""

from dataclasses import dataclass, field

# Aggregate functions a Select may apply. Each adapter maps these to its own
# spelling (InfluxQL `mean`, SQL `avg`, ...). None means "the raw column".
AGG_FUNCTIONS = ("mean", "min", "max", "count", "sum", "first", "last")


@dataclass(frozen=True)
class Select:
    """One selected column: an aggregate of a field, or the raw field.

    `alias` is the column name the result carries, and callers read results by
    it — so it matches InfluxDB's own naming (the function name, e.g. "mean";
    "time" for the timestamp; the field name for a raw select). Adapters must
    label their output columns with these aliases regardless of dialect.
    """

    field: str
    fn: str | None = None  # None = raw column; else one of AGG_FUNCTIONS

    @property
    def alias(self) -> str:
        return self.fn if self.fn else self.field


@dataclass(frozen=True)
class TagFilter:
    """A tag constrained to one value, or to any of several (an OR).

    Several values is how a location that exists under multiple capitalisations
    (AirLock / Airlock) is matched without silently reading only one of them.
    """

    key: str
    values: tuple[str, ...]


@dataclass(frozen=True)
class TimeWindow:
    """When to read over. Exactly one kind is in force.

    kind="all"       every point on record.
    kind="relative"  the last `minutes`, ending now.
    kind="absolute"  from `start` and/or to `end` (ISO 8601 instants).
    """

    kind: str = "all"  # "all" | "relative" | "absolute"
    minutes: int = 0
    start: str | None = None
    end: str | None = None


@dataclass(frozen=True)
class GroupBy:
    """How to group the rows.

    tags        group by these named tag keys.
    all_tags    group by every tag (InfluxQL `GROUP BY *`) — for per-series
                statistics where the caller does not enumerate the tags.
    bucket_minutes / offset_minutes  a `GROUP BY time(...)` bucket, optionally
                shifted off UTC midnight so buckets align to the habitat's day.
    fill_none   drop empty buckets rather than zero-filling them.
    """

    tags: tuple[str, ...] = ()
    all_tags: bool = False
    bucket_minutes: int | None = None
    offset_minutes: int = 0
    fill_none: bool = True


@dataclass(frozen=True)
class Query:
    """A single read against the habitat data source.

    Built by the telemetry layer, rendered by an adapter. `order_desc` with
    `limit=1` is how a point read ("the latest value") is expressed portably —
    ORDER BY time then take one — so the returned timestamp is unambiguously
    that of the actual point.
    """

    measurement: str
    selects: tuple[Select, ...]
    filters: tuple[TagFilter, ...] = ()
    window: TimeWindow = field(default_factory=TimeWindow)
    group_by: GroupBy | None = None
    order_desc: bool | None = None  # None = unordered; True/False = ORDER BY time
    limit: int | None = None
