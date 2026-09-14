"""The data-source layer - ATLAS Core's only door to a habitat database.

    ATLAS Core (telemetry, tools, services)
        -> get_data_source().run(Query)         # this module
            -> the active DataSource adapter    # chosen by DATA_SOURCE
                -> the habitat database

Core code asks for the active adapter and never names one:

    from app.datasource import get_data_source

Which adapter answers is decided once, from the `DATA_SOURCE` setting, by
`get_data_source()`. Adding a backend means writing a `DataSource` subclass and
registering it in `ADAPTERS` below - no change to any caller.

Registered adapters:

    sqlite    A local SQLite readings table. What the bundled demo uses, and
              the default when DATA_SOURCE is unset.
    sql       An existing SQL database (Postgres/MySQL/Timescale) you map.
    influxdb  Direct InfluxDB 1.x over its HTTP query API.
    grafana   Grafana proxy - reach an InfluxDB 1.x through Grafana.

No adapter is privileged: each is one implementation of the same interface.

The module-level `influxql()` below is NOT part of that path. It is the raw
InfluxQL escape hatch, used only by the InfluxQL diagnostic scripts and
available only on adapters that declare `raw_influxql`.
"""

from collections.abc import Callable

from app.config import get_settings
from app.core.errors import ConfigurationError
from app.core.logging import get_logger
from app.datasource.base import DataSource

log = get_logger(__name__)


def _make_grafana() -> DataSource:
    from app.datasource.grafana import GrafanaDataSource

    return GrafanaDataSource()


def _make_influxdb() -> DataSource:
    from app.datasource.influxdb import InfluxDBDataSource

    return InfluxDBDataSource()


def _make_sqlite() -> DataSource:
    from app.datasource.sqlite import SqliteDataSource

    return SqliteDataSource()


def _make_sql() -> DataSource:
    from app.datasource.sql import SqlDataSource

    return SqlDataSource()


# name -> factory. A new adapter is one entry here plus its module.
ADAPTERS: dict[str, Callable[[], DataSource]] = {
    "grafana": _make_grafana,
    "influxdb": _make_influxdb,
    "sqlite": _make_sqlite,
    "sql": _make_sql,
}

_active: DataSource | None = None


def get_data_source() -> DataSource:
    """The process-wide data source, built once from DATA_SOURCE.

    Cached in a module global rather than lru_cache so tests and the discovery
    scripts can drop it with `reset()` after changing settings.
    """
    global _active
    if _active is None:
        name = (get_settings().data_source or "sqlite").strip().lower()
        factory = ADAPTERS.get(name)
        if factory is None:
            known = ", ".join(sorted(ADAPTERS))
            raise ConfigurationError(
                f"Unknown DATA_SOURCE {name!r}. Known adapters: {known}."
            )
        _active = factory()
        log.debug("Data source: %s", _active.describe())
    return _active


def reset() -> None:
    """Forget the built adapter. For tests and scripts that repoint settings."""
    global _active
    _active = None


def influxql(query: str, db: str | None = None, uid: str | None = None) -> dict:
    """Run a read-only InfluxQL query against the active habitat data source.

    For the InfluxQL diagnostic scripts only. Adapters that do not speak
    InfluxQL raise `CapabilityError`, which is the expected answer on SQLite
    and SQL habitats. Nothing in the request path calls this.
    """
    return get_data_source().influxql(query, db=db, uid=uid)
