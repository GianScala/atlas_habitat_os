"""Grafana proxy adapter — reach a habitat InfluxDB through Grafana.

Grafana holds the InfluxDB 1.x credentials and proxies our queries, so ATLAS
needs no InfluxDB token of its own. This is the reference adapter and the one
our own habitat runs on; it is one implementation of `DataSource`, not a core
dependency of ATLAS.

The database is InfluxDB 1.x and speaks InfluxQL. Read-only enforcement and
response parsing live in `wire.py`, shared with the direct-InfluxDB adapter.

The module also exposes Grafana-specific discovery — `list_datasources`,
`list_dashboards`, `get_dashboard` — used only by the diagnostic scripts, not by
the ATLAS request path. They are Grafana admin operations and stay here rather
than on the generic interface.
"""

import threading
from typing import Any

import requests

from app.config import get_settings
from app.core.errors import ConfigurationError, DatasourceError
from app.core.logging import get_logger
from app.datasource.influxql_base import InfluxQLDataSource
from app.datasource.wire import assert_read_only, parse_influx_response

log = get_logger(__name__)


# --------------------------------------------------------------------------
# HTTP plumbing
# --------------------------------------------------------------------------


def _check_config() -> None:
    settings = get_settings()
    if not settings.grafana_base:
        raise ConfigurationError("GRAFANA_URL is not set. Fill in your .env file.")
    if not settings.has_grafana_credentials:
        raise ConfigurationError(
            "No Grafana credentials. Set GRAFANA_TOKEN, or both GRAFANA_USER "
            "and GRAFANA_PASS, in your .env file."
        )


def _auth_kind() -> str:
    settings = get_settings()
    if settings.grafana_token:
        return "Bearer token"
    return f"basic auth as {settings.grafana_user!r}"


# One session per thread, kept for the life of the thread.
#
# A dashboard is a dozen queries. Building a fresh `requests.Session` for each
# of them throws away the connection as soon as the query lands, so every panel
# pays a TCP handshake — and a TLS one against an https Grafana — before it can
# ask its question. Held open, the same connection answers all twelve.
#
# Thread-local rather than one shared session, because the panels are fetched
# concurrently (see `core/concurrency.py`) and `requests.Session` is not
# documented as thread-safe. Each worker thread keeps its own, which is what
# makes a warm pool of threads worth having.
_sessions = threading.local()


def _session() -> requests.Session:
    """This thread's session, carrying whichever credential we have. Token wins."""
    _check_config()

    existing: requests.Session | None = getattr(_sessions, "session", None)
    if existing is not None:
        return existing

    settings = get_settings()
    session = requests.Session()
    session.headers["Accept"] = "application/json"
    if settings.grafana_token:
        session.headers["Authorization"] = f"Bearer {settings.grafana_token}"
    else:
        session.auth = (settings.grafana_user, settings.grafana_pass)

    _sessions.session = session
    return session


def _get(path: str, params: dict | None = None) -> requests.Response:
    """GET a Grafana path, translating every failure into a plain reason."""
    settings = get_settings()
    url = f"{settings.grafana_base}{path}"

    try:
        response = _session().get(url, params=params, timeout=settings.datasource_timeout)
    except requests.exceptions.ConnectionError as exc:
        raise DatasourceError(
            f"Cannot reach Grafana at {settings.grafana_base} — "
            f"{exc.__class__.__name__}. Are you on the habitat network?"
        ) from exc
    except requests.exceptions.Timeout as exc:
        raise DatasourceError(
            f"Grafana at {settings.grafana_base} timed out after "
            f"{settings.datasource_timeout}s."
        ) from exc

    if response.status_code == 401:
        raise DatasourceError(
            f"HTTP 401 Unauthorized from {url} using {_auth_kind()}. Grafana "
            "rejected the credentials — check GRAFANA_TOKEN or "
            "GRAFANA_USER/GRAFANA_PASS."
        )
    if response.status_code == 403:
        raise DatasourceError(
            f"HTTP 403 Forbidden from {url} using {_auth_kind()}. The "
            "credentials are valid but lack permission for this endpoint."
        )
    if not response.ok:
        raise DatasourceError(f"HTTP {response.status_code} from {url}: {response.text[:400]}")
    return response


# --------------------------------------------------------------------------
# Datasource discovery
# --------------------------------------------------------------------------


def _normalise_datasource(raw: dict) -> dict:
    """The handful of fields we care about, across Grafana versions.

    Grafana has moved the InfluxDB 1.x database name around between releases:
    older builds put it in a top-level "database", newer ones in
    jsonData.dbName. Check both.
    """
    json_data = raw.get("jsonData") or {}
    return {
        "id": raw.get("id"),
        "uid": raw.get("uid"),
        "name": raw.get("name"),
        "type": raw.get("type"),
        "database": raw.get("database") or json_data.get("dbName") or "",
    }


def list_datasources() -> list[dict]:
    """Datasources this Grafana knows about.

    Primary path is /api/datasources, which needs admin rights. A viewer-level
    account falls back to /api/frontend/settings, which carries the same
    id/uid/name/type/database fields.
    """
    try:
        return [_normalise_datasource(d) for d in _get("/api/datasources").json()]
    except DatasourceError as exc:
        if "403" not in str(exc):
            raise
        log.info("Datasource listing needs admin rights; using frontend settings.")
        settings_bundle = _get("/api/frontend/settings").json()
        found = (settings_bundle.get("datasources") or {}).values()
        return [_normalise_datasource(d) for d in found if isinstance(d, dict)]


def get_datasource(uid: str | None = None) -> dict:
    """One datasource, normalised. Defaults to the configured one."""
    uid = uid or get_settings().grafana_datasource_uid
    if not uid:
        raise ConfigurationError("GRAFANA_DATASOURCE_UID is not set in .env.")

    datasources = list_datasources()
    for datasource in datasources:
        if datasource["uid"] == uid:
            return datasource

    known = ", ".join(f'{d["name"]} ({d["uid"]})' for d in datasources) or "none"
    raise DatasourceError(f"No datasource with uid {uid!r} in this Grafana. Found: {known}")


# Resolved database names, by datasource uid.
#
# Without INFLUX_DB set, the name is discovered by listing Grafana's
# datasources — and every query needs it, so an undiscovered name meant a
# second HTTP round trip in front of each one. A twelve-panel dashboard made
# twenty-four requests to answer twelve questions.
#
# Cached for the life of the process, which is the same lifetime the settings
# have: a datasource repointed at another database is a restart either way.
# `reset_datasource_cache()` is for the discovery scripts, which repoint on
# purpose while running.
_databases: dict[str, str] = {}
_databases_lock = threading.Lock()


def reset_datasource_cache() -> None:
    """Forget resolved database names. For scripts that change the target."""
    with _databases_lock:
        _databases.clear()


def database_name(uid: str | None = None) -> str:
    """The InfluxDB database to query, from .env or the datasource itself."""
    settings = get_settings()
    if settings.influx_db and uid in (None, settings.grafana_datasource_uid):
        return settings.influx_db

    key = uid or settings.grafana_datasource_uid
    cached = _databases.get(key)
    if cached is not None:
        return cached

    database = get_datasource(uid)["database"]
    if not database:
        raise ConfigurationError(
            f"Grafana did not report a database name for datasource "
            f"{uid or settings.grafana_datasource_uid!r}. Set INFLUX_DB in .env "
            "to name it explicitly."
        )

    with _databases_lock:
        _databases[key] = database
    return database


# --------------------------------------------------------------------------
# Dashboards — read to learn the habitat's conventions, never to answer from
# --------------------------------------------------------------------------


def list_dashboards() -> list[dict]:
    """Every dashboard Grafana will show us, with its folder and uid."""
    response = _get("/api/search", params={"type": "dash-db", "limit": 5000})
    return [
        {
            "uid": d.get("uid"),
            "title": d.get("title"),
            "folder": d.get("folderTitle") or "General",
        }
        for d in response.json()
    ]


def get_dashboard(uid: str) -> dict:
    """One dashboard's full JSON definition, panels included."""
    return _get(f"/api/dashboards/uid/{uid}").json()


# --------------------------------------------------------------------------
# Querying
# --------------------------------------------------------------------------


def influxql(query: str, db: str | None = None, uid: str | None = None) -> dict:
    """Run an InfluxQL query through the Grafana proxy and return parsed results."""
    assert_read_only(query)
    database = db or database_name(uid)
    target_uid = uid or get_settings().grafana_datasource_uid

    log.debug("influxql db=%s: %s", database, query)
    payload = _proxy_query(query, database, target_uid)
    return parse_influx_response(payload, query, database)


def _proxy_query(query: str, database: str, uid: str) -> dict:
    """Send an InfluxQL query through the Grafana datasource proxy.

    Grafana forwards /query to InfluxDB using its own stored credentials, so
    we never need an InfluxDB token ourselves.

    The uid-based proxy path is preferred; older Grafana builds only expose
    the numeric-id proxy, so fall back to that.
    """
    params: dict[str, Any] = {"db": database, "q": query}

    try:
        return _get(f"/api/datasources/proxy/uid/{uid}/query", params=params).json()
    except DatasourceError as exc:
        if "404" not in str(exc):
            raise  # a real failure (auth, influx error) — do not mask it

    numeric_id = get_datasource(uid)["id"]
    if numeric_id is None:
        raise DatasourceError(
            f"The uid proxy path returned 404 and Grafana did not report a "
            f"numeric id for datasource {uid!r}."
        )
    return _get(f"/api/datasources/proxy/{numeric_id}/query", params=params).json()


# --------------------------------------------------------------------------
# The adapter object the registry hands to ATLAS Core
# --------------------------------------------------------------------------


class GrafanaDataSource(InfluxQLDataSource):
    """Reach a habitat InfluxDB through Grafana's datasource proxy.

    Supplies the two transport methods the shared InfluxQL base needs; the
    module functions above hold the pooled HTTP sessions and the
    resolved-database cache at process scope.
    """

    label = "Grafana proxy"

    def _fetch(self, query: str, database: str, uid: str | None) -> dict:
        target_uid = uid or get_settings().grafana_datasource_uid
        return _proxy_query(query, database, target_uid)

    def _database(self, uid: str | None = None) -> str:
        return database_name(uid)

    def configured(self) -> bool:
        settings = get_settings()
        return bool(settings.grafana_base and settings.has_grafana_credentials)

    def describe(self) -> str:
        settings = get_settings()
        return (
            f"Grafana proxy at {settings.grafana_base or '(unset)'} "
            f"datasource {settings.grafana_datasource_uid or '(unset)'}"
        )
