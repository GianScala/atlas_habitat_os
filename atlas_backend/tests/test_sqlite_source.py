"""The SQLite adapter — proof the structured interface is real.

A non-InfluxDB backend answering the same `Query` and returning the same series
shape means the whole telemetry layer works on it unchanged. These build a tiny
SQLite habitat and drive the adapter directly.
"""

import sqlite3
from datetime import UTC

import pytest

import app.datasource as ds
from app.config import get_settings
from app.datasource.query import GroupBy, Query, Select, TagFilter, TimeWindow
from app.datasource.sqlite import _SCHEMA, SqliteDataSource

# A day of two rooms reporting Temperature, on the hour, plus a cumulative meter.
_DAY = 86400
_T0 = 1_700_000_000  # a fixed epoch; the tests use absolute windows around it


@pytest.fixture()
def sqlite_habitat(tmp_path, monkeypatch):
    path = tmp_path / "habitat.db"
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    rows = []
    for hour in range(24):
        ts = _T0 + hour * 3600
        rows.append(("Temperature", "Greenhouse", "value", float(ts), 20.0 + hour * 0.1))
        rows.append(("Temperature", "Airlock", "value", float(ts), 5.0 + hour * 0.2))
        rows.append(("Energy", "Greenhouse", "total_kwh", float(ts), 100.0 + hour * 2.0))
    conn.executemany(
        "INSERT INTO readings (measurement, location, field, ts, value) VALUES (?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(get_settings(), "sqlite_path", str(path))
    monkeypatch.setattr(get_settings(), "data_source", "sqlite")
    ds.reset()
    yield path
    ds.reset()


class TestDiscovery:
    def test_lists_measurements(self, sqlite_habitat):
        assert SqliteDataSource().measurements() == ["Energy", "Temperature"]

    def test_reports_locations_under_the_profiles_tag_key(self, sqlite_habitat):
        source = SqliteDataSource()
        assert source.tag_keys("Temperature") == ["Location"]
        assert source.tag_values("Temperature", "Location") == ["Airlock", "Greenhouse"]

    def test_fields(self, sqlite_habitat):
        assert SqliteDataSource().field_keys("Energy") == [
            {"field": "total_kwh", "type": "float"}
        ]


class TestPointReads:
    def test_latest_returns_the_last_point(self, sqlite_habitat):
        q = Query(
            "Temperature",
            (Select("value"),),
            (TagFilter("Location", ("Greenhouse",)),),
            order_desc=True,
            limit=1,
        )
        result = SqliteDataSource().run(q)
        series = result["series"][0]
        assert series["columns"] == ["time", "value"]
        # hour 23 -> 20.0 + 2.3
        assert series["values"][0][1] == pytest.approx(22.3)


class TestAggregates:
    def test_whole_window_mean_min_max(self, sqlite_habitat):
        # No bucket -> one figure over the whole window, like summarize's
        # overall query. (A daily bucket would split on the UTC-midnight
        # boundary exactly as InfluxDB does, which is a separate behaviour.)
        q = Query(
            "Temperature",
            (Select("value", "mean"), Select("value", "min"), Select("value", "max")),
            (TagFilter("Location", ("Greenhouse",)),),
            TimeWindow("absolute", start=_iso(_T0), end=_iso(_T0 + _DAY)),
        )
        result = SqliteDataSource().run(q)
        series = result["series"][0]
        row = dict(zip(series["columns"], series["values"][0], strict=False))
        assert row["min"] == pytest.approx(20.0)
        assert row["max"] == pytest.approx(22.3)
        assert row["mean"] == pytest.approx(sum(20.0 + h * 0.1 for h in range(24)) / 24)

    def test_group_by_all_tags_yields_one_series_per_location(self, sqlite_habitat):
        q = Query(
            "Temperature",
            (Select("value", "count"),),
            (),
            TimeWindow("absolute", start=_iso(_T0), end=_iso(_T0 + _DAY)),
            GroupBy(all_tags=True),
        )
        result = SqliteDataSource().run(q)
        locations = {s["tags"]["Location"] for s in result["series"]}
        assert locations == {"Greenhouse", "Airlock"}

    def test_consumption_first_and_last_bracket_the_meter(self, sqlite_habitat):
        q = Query(
            "Energy",
            (Select("total_kwh", "first"), Select("total_kwh", "last")),
            (TagFilter("Location", ("Greenhouse",)),),
            TimeWindow("absolute", start=_iso(_T0), end=_iso(_T0 + _DAY)),
            GroupBy(all_tags=True),
        )
        result = SqliteDataSource().run(q)
        series = result["series"][0]
        row = dict(zip(series["columns"], series["values"][0], strict=False))
        assert row["first"] == pytest.approx(100.0)  # hour 0
        assert row["last"] == pytest.approx(100.0 + 23 * 2.0)  # hour 23


class TestCapabilities:
    def test_sqlite_does_not_offer_raw_influxql(self, sqlite_habitat):
        from app.datasource.base import CAP_RAW_INFLUXQL

        assert not SqliteDataSource().supports(CAP_RAW_INFLUXQL)


def _iso(epoch: int) -> str:
    from datetime import datetime

    return datetime.fromtimestamp(epoch, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
