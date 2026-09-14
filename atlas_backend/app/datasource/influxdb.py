"""Direct InfluxDB 1.x adapter — talk to InfluxDB without Grafana in front.

The counterpart to the Grafana proxy adapter: same database, same InfluxQL,
same parsed shape, but connecting straight to InfluxDB's HTTP `/query` endpoint
with a token (or user/pass) of our own. Everything except the transport is
inherited from `InfluxQLDataSource`.

    GET {INFLUX_URL}/query?db={INFLUX_DB}&q={query}
    Authorization: Token {INFLUX_TOKEN}          # or HTTP basic auth

Select it with `DATA_SOURCE=influxdb` and set the `INFLUX_*` variables.
"""

import threading

import requests

from app.config import get_settings
from app.core.errors import ConfigurationError, DatasourceError
from app.core.logging import get_logger
from app.datasource.influxql_base import InfluxQLDataSource

log = get_logger(__name__)

# One pooled session per thread, for the same reason the Grafana adapter keeps
# one: a dashboard is a dozen concurrent queries and a fresh session per query
# throws the connection away each time.
_sessions = threading.local()


def _check_config() -> None:
    settings = get_settings()
    if not settings.influx_url:
        raise ConfigurationError(
            "INFLUX_URL is not set. Fill it in, or set DATA_SOURCE=grafana."
        )
    if not settings.influx_db:
        raise ConfigurationError(
            "INFLUX_DB is not set — the direct InfluxDB adapter needs the "
            "database name to query."
        )


def _session() -> requests.Session:
    """This thread's session, carrying whichever credential we have. Token wins."""
    _check_config()

    existing: requests.Session | None = getattr(_sessions, "session", None)
    if existing is not None:
        return existing

    settings = get_settings()
    session = requests.Session()
    session.headers["Accept"] = "application/json"
    if settings.influx_token:
        session.headers["Authorization"] = f"Token {settings.influx_token}"
    elif settings.influx_user:
        session.auth = (settings.influx_user, settings.influx_pass)

    _sessions.session = session
    return session


class InfluxDBDataSource(InfluxQLDataSource):
    """Reach a habitat InfluxDB directly over its HTTP query API."""

    label = "InfluxDB (direct)"

    def _database(self, uid: str | None = None) -> str:
        return get_settings().influx_db

    def _fetch(self, query: str, database: str, uid: str | None) -> dict:
        settings = get_settings()
        url = f"{settings.influx_base}/query"
        log.debug("influxql (direct) db=%s: %s", database, query)
        try:
            response = _session().get(
                url,
                params={"db": database, "q": query},
                timeout=settings.datasource_timeout,
            )
        except requests.exceptions.ConnectionError as exc:
            raise DatasourceError(
                f"Cannot reach InfluxDB at {settings.influx_base} — "
                f"{exc.__class__.__name__}. Is the database up and reachable?"
            ) from exc
        except requests.exceptions.Timeout as exc:
            raise DatasourceError(
                f"InfluxDB at {settings.influx_base} timed out after "
                f"{settings.datasource_timeout}s."
            ) from exc

        if response.status_code in (401, 403):
            raise DatasourceError(
                f"HTTP {response.status_code} from {url}. InfluxDB rejected the "
                "credentials — check INFLUX_TOKEN or INFLUX_USER/INFLUX_PASS."
            )
        if not response.ok:
            raise DatasourceError(
                f"HTTP {response.status_code} from {url}: {response.text[:400]}"
            )
        return response.json()

    def configured(self) -> bool:
        settings = get_settings()
        return bool(settings.influx_url and settings.influx_db)

    def describe(self) -> str:
        settings = get_settings()
        return (
            f"InfluxDB (direct) at {settings.influx_base or '(unset)'} "
            f"db {settings.influx_db or '(unset)'}"
        )
