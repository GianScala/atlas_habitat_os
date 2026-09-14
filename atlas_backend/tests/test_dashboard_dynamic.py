"""The dashboard adapts to the connected database.

Two promises: a panel for a sensor the database does not have is hidden rather
than drawn empty, and a habitat can declare its own panels in its profile.
"""

import sqlite3

import pytest

import app.datasource as ds
import app.datasource.sqlite as sqlmod
from app.config import get_settings
from app.habitat import reset as reset_profile
from app.services import dashboard as dash


@pytest.fixture()
def only_temperature(tmp_path, monkeypatch):
    """A SQLite habitat that records Temperature and nothing else."""
    path = tmp_path / "hab.db"
    conn = sqlite3.connect(path)
    conn.executescript(sqlmod._SCHEMA)
    conn.executemany(
        "INSERT INTO readings (measurement, location, field, ts, value) VALUES (?,?,?,?,?)",
        [("Temperature", "RoomA", "value", 1_700_000_000.0 + h * 3600, 20.0) for h in range(5)],
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(get_settings(), "data_source", "sqlite")
    monkeypatch.setattr(get_settings(), "sqlite_path", str(path))
    ds.reset()
    discovery_reset()
    yield path
    ds.reset()
    discovery_reset()


def discovery_reset():
    from app.telemetry import discovery

    discovery.reset_cache()


class TestAvailabilityFilter:
    def test_hides_panels_whose_measurement_is_absent(self, only_temperature):
        panels = (
            dash.Panel(
                id="t", title="T", subtitle="", measurement="Temperature", field="value"
            ),
            dash.Panel(id="w", title="W", subtitle="", measurement="Water", field="litres"),
        )
        kept = {p.id for p in dash._available(panels)}
        assert kept == {"t"}

    def test_hides_panels_whose_field_is_absent(self, only_temperature):
        panels = (
            dash.Panel(
                id="ok", title="", subtitle="", measurement="Temperature", field="value"
            ),
            dash.Panel(
                id="bad", title="", subtitle="", measurement="Temperature", field="humidity"
            ),
        )
        kept = {p.id for p in dash._available(panels)}
        assert kept == {"ok"}

    def test_a_full_catalogue_shrinks_to_what_the_database_has(self, only_temperature):
        # A twelve-panel habitat pointed at a database that records only
        # Temperature keeps its temperature chart and drops everything else.
        reset_profile()
        declared = dash.catalogue()
        assert len(declared) == 12
        kept = {p.id for p in dash._available(declared)}
        assert kept == {"room_temperature"}


class TestProfilePanels:
    def test_no_profile_panels_derives_a_catalogue_from_the_database(
        self, only_temperature, monkeypatch
    ):
        # A habitat that declares no panels still gets a dashboard: the one
        # measurement it records, charted per location.
        from app.habitat.profile import HabitatProfile

        monkeypatch.setattr(dash, "profile", lambda: HabitatProfile())
        derived = dash.catalogue()
        assert [p.id for p in derived] == ["room_temperature"]
        assert derived[0].group_by == "Location"

    def test_a_profile_can_declare_its_own_panels(self, only_temperature, monkeypatch):
        from app.habitat.profile import HabitatProfile

        fake = HabitatProfile(
            dashboard_panels=(
                {
                    "id": "room_temperature",
                    "title": "Temp",
                    "measurement": "Temperature",
                    "field": "value",
                    "group_by": "Location",
                    "group": "Environment",
                },
            )
        )
        monkeypatch.setattr(dash, "profile", lambda: fake)
        built = dash.catalogue()
        assert [p.id for p in built] == ["room_temperature"]
        assert built[0].group_by == "Location"


class TestMissionResourcesFromProfile:
    def test_meters_and_defaults_come_from_the_profile(self, tmp_path, monkeypatch):
        from app.mission import meters, plan

        path = tmp_path / "hab.yaml"
        path.write_text(
            """
name: PowerOnly
mission_resources:
  - key: power
    label: Habitat power
    kind: cumulative
    measurement: Energy
    field: total_kwh
    default_daily: 30.0
""",
            encoding="utf-8",
        )
        monkeypatch.setattr(get_settings(), "habitat_config", str(path))
        reset_profile()

        got = meters._meters_from_profile()
        assert [(m.key, m.kind, m.measurement, m.field) for m in got] == [
            ("power", "cumulative", "Energy", "total_kwh")
        ]
        # And this habitat budgets only power.
        assert plan._resources_from_profile() == {"power": "Habitat power"}
        reset_profile()
