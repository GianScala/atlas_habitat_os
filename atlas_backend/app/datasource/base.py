"""The data-source interface — ATLAS Core's one seam to a habitat database.

    ATLAS Core -> DataSource (this interface) -> adapter -> habitat database

The telemetry layer talks to the habitat only through this interface, and it
does so at TWO levels:

  * the STRUCTURED level (`run` + the discovery methods) — database-neutral.
    The telemetry layer builds a `Query` (see `query.py`) and every adapter can
    answer it, whatever its dialect. This is the level that makes ATLAS work on
    InfluxDB, SQLite, Postgres, or anything else.

  * the RAW level (`influxql`) — an InfluxQL string straight through. A few
    advanced analyses (tank-flow reconciliation, the charting time-series) are
    still expressed as InfluxQL and run only on adapters that declare the
    `raw_influxql` capability. Porting them to the structured level is what
    makes them database-agnostic too; until then the tools that need them are
    offered only when the active adapter supports them.

Adapters advertise what they can do with `capabilities`, and the tool registry
offers the model only the tools its data source can actually answer.
"""

from abc import ABC, abstractmethod

from app.core.errors import DatasourceError
from app.datasource.query import Query

# Capability names an adapter may advertise.
CAP_QUERY = "query"  # structured run() + discovery. Every adapter has this.
CAP_RAW_INFLUXQL = "raw_influxql"  # accepts raw InfluxQL strings via influxql().


class CapabilityError(DatasourceError):
    """Raised when a tool needs a capability the active data source lacks."""


class DataSource(ABC):
    """A habitat telemetry backend ATLAS can query, read-only.

    A `Result` is a plain dict: {"query": <rendered text>, "series": [
        {"name", "tags": {...}, "columns": [...], "values": [[...], ...]}]}.
    `query` is the human-readable query that ran, in the adapter's own dialect,
    and is shown to the crew as provenance. `series` is what the analysis reads.
    """

    #: Short human label for logs and the health endpoint, e.g. "Grafana proxy".
    label: str = "data source"

    #: What this adapter can do. At minimum {CAP_QUERY}.
    capabilities: frozenset[str] = frozenset({CAP_QUERY})

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities

    # --- structured level (database-neutral) ------------------------------

    @abstractmethod
    def run(self, query: Query) -> dict:
        """Execute a structured Query and return a Result dict."""

    @abstractmethod
    def measurements(self) -> list[str]:
        """Every measurement name in the database."""

    @abstractmethod
    def field_keys(self, measurement: str) -> list[dict]:
        """Field keys and types: [{"field": str, "type": str}, ...]."""

    @abstractmethod
    def tag_keys(self, measurement: str) -> list[str]:
        """Tag keys on one measurement."""

    @abstractmethod
    def tag_values(self, measurement: str, tag_key: str) -> list[str]:
        """Every value a tag key takes on one measurement."""

    def schema_index(self) -> dict[str, dict[str, list[str]]] | None:
        """Whole-schema {measurement: {"fields": [...], "tags": [...]}}, if cheap.

        An optional fast path for `find_measurements`. Return None to have the
        caller build it per-measurement instead.
        """
        return None

    # --- raw level (InfluxQL only) ----------------------------------------

    def influxql(
        self, query: str, db: str | None = None, uid: str | None = None
    ) -> dict:
        """Run a raw InfluxQL string. Only adapters with CAP_RAW_INFLUXQL."""
        raise CapabilityError(
            f"{self.label} does not accept raw InfluxQL. This capability "
            "(tank-flow, charts) needs an InfluxQL-speaking data source."
        )

    # --- configuration / identity -----------------------------------------

    @abstractmethod
    def configured(self) -> bool:
        """True when this adapter has the settings it needs to connect."""

    def describe(self) -> str:
        """One line naming where this adapter points, for logs and health."""
        return self.label
