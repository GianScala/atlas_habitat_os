"""The SQL mapping adapter — a habitat's own relational schema, unchanged.

The point of these: a table that looks NOTHING like ATLAS's model
(sensor_readings with sensor_id / room / metric_type / reading_ts /
reading_value) is served purely through the profile's `sql_mapping`, with no
data migration. Tested over sqlite via the stdlib DB-API, which is the same code
path Postgres/MySQL take with a different driver.
"""

import sqlite3
from datetime import UTC

import pytest

import app.datasource as ds
import app.datasource.sql as sqlmod
from app.config import get_settings
from app.datasource.query import GroupBy, Query, Select, TagFilter, TimeWindow
from app.habitat.profile import HabitatProfile

_T0 = 1_700_000_000
_MAPPING = {
    "table": "sensor_readings",
    "measurement_column": "metric_type",
    "location_column": "room",
    "time_column": "reading_ts",
    "value_column": "reading_value",
    "time_encoding": "epoch",
}


@pytest.fixture()
def sql_habitat(tmp_path, monkeypatch):
    path = tmp_path / "plant.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE sensor_readings (sensor_id TEXT, room TEXT, "
        "metric_type TEXT, reading_ts REAL, reading_value REAL)"
    )
    rows = []
    for hour in range(24):
        ts = float(_T0 + hour * 3600)
        rows.append(("s1", "GreenhouseA", "temperature", ts, 20.0 + hour * 0.1))
        rows.append(("s2", "GreenhouseB", "temperature", ts, 15.0 + hour * 0.2))
        rows.append(("s3", "GreenhouseA", "co2", ts, 500.0 + hour))
    conn.executemany("INSERT INTO sensor_readings VALUES (?,?,?,?,?)", rows)
    conn.commit()
    conn.close()

    fake = HabitatProfile(
        name="PlantSim",
        location_tag_keys=("Location",),
        units={"temperature": {"value": "°C"}, "co2": {"value": "ppm"}},
        sql_mapping=_MAPPING,
    )
    monkeypatch.setattr(sqlmod, "profile", lambda: fake)
    monkeypatch.setattr(get_settings(), "data_source", "sql")
    monkeypatch.setattr(get_settings(), "sql_dsn", f"sqlite:///{path}")
    ds.reset()
    yield path
    ds.reset()


class TestDiscovery:
    def test_measurements_come_from_the_mapped_column(self, sql_habitat):
        assert sqlmod.SqlDataSource().measurements() == ["co2", "temperature"]

    def test_locations_come_from_the_mapped_room_column(self, sql_habitat):
        src = sqlmod.SqlDataSource()
        assert src.tag_keys("temperature") == ["Location"]
        assert src.tag_values("temperature", "Location") == ["GreenhouseA", "GreenhouseB"]

    def test_co2_only_lives_in_greenhouse_a(self, sql_habitat):
        assert sqlmod.SqlDataSource().tag_values("co2", "Location") == ["GreenhouseA"]


class TestReads:
    def test_latest_reads_the_mapped_value_column(self, sql_habitat):
        q = Query(
            "temperature",
            (Select("value"),),
            (TagFilter("Location", ("GreenhouseA",)),),
            order_desc=True,
            limit=1,
        )
        series = sqlmod.SqlDataSource().run(q)["series"][0]
        assert series["values"][0][1] == pytest.approx(22.3)  # hour 23

    def test_whole_window_stats(self, sql_habitat):
        q = Query(
            "temperature",
            (Select("value", "mean"), Select("value", "min"), Select("value", "max")),
            (TagFilter("Location", ("GreenhouseA",)),),
            TimeWindow("absolute", start=_iso(_T0), end=_iso(_T0 + 86400)),
        )
        row = _row(sqlmod.SqlDataSource().run(q))
        assert row["min"] == pytest.approx(20.0)
        assert row["max"] == pytest.approx(22.3)

    def test_group_by_all_tags_separates_the_two_greenhouses(self, sql_habitat):
        q = Query(
            "temperature",
            (Select("value", "count"),),
            (),
            TimeWindow("absolute", start=_iso(_T0), end=_iso(_T0 + 86400)),
            GroupBy(all_tags=True),
        )
        result = sqlmod.SqlDataSource().run(q)
        got = {s["tags"]["Location"]: s["values"][0][1] for s in result["series"]}
        assert got == {"GreenhouseA": 24, "GreenhouseB": 24}


class TestMappingVariants:
    def test_a_table_without_a_field_column_defaults_to_value(self, sql_habitat, monkeypatch):
        # metric_type IS the measurement; there is no separate field column, so
        # every row's field is "value" — the common single-value-per-row shape.
        fake = HabitatProfile(location_tag_keys=("Location",), sql_mapping=_MAPPING)
        monkeypatch.setattr(sqlmod, "profile", lambda: fake)
        assert sqlmod.SqlDataSource().field_keys("temperature") == [
            {"field": "value", "type": "float"}
        ]

    def test_capabilities_exclude_raw_influxql(self, sql_habitat):
        from app.datasource.base import CAP_RAW_INFLUXQL

        assert not sqlmod.SqlDataSource().supports(CAP_RAW_INFLUXQL)


def _iso(epoch: int) -> str:
    from datetime import datetime

    return datetime.fromtimestamp(epoch, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row(result: dict) -> dict:
    s = result["series"][0]
    return dict(zip(s["columns"], s["values"][0], strict=False))


def test_sqlite_adapter_cannot_write(sql_habitat):
    import sqlite3

    conn, _ = sqlmod._connect()
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("CREATE TABLE forbidden (value INTEGER)")
    finally:
        conn.close()


def test_mysql_uses_compatible_identifier_mode():
    params = sqlmod._mysql_params("mysql://demo:p%40ss@localhost/example")
    assert params["password"] == "p@ss"
    assert params["sql_mode"] == "ANSI_QUOTES"
    assert params["init_command"] == "SET SESSION TRANSACTION READ ONLY"
    assert params["connect_timeout"] > 0
