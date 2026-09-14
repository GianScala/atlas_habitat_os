"""Habitat-driven analysis and tool set — every station-specific assumption is
now configuration. Instrument deadbands, consumption-rollup tags, the phased meter,
and which tanks exist all come from the habitat profile, and the tool set the
model is offered follows from them.
"""

import pytest

from app.config import get_settings
from app.habitat import profile as habitat_profile
from app.habitat import reset as reset_profile


@pytest.fixture()
def habitat(tmp_path, monkeypatch):
    """Load a given YAML profile for the duration of one test."""

    def _load(yaml_text: str):
        path = tmp_path / "hab.yaml"
        path.write_text(yaml_text, encoding="utf-8")
        monkeypatch.setattr(get_settings(), "habitat_config", str(path))
        reset_profile()
        return habitat_profile()

    yield _load
    reset_profile()


FULL_HABITAT = """
name: TestHab
aggregate_tag_values: [gridsupply, habitat]
noise_floors:
  Water: { litres: 1.0 }
electrical:
  measurement: Electricity
  phase_tag: Phase
  phases: ["1", "2", "3"]
stocks:
  - key: clean_water
    label: Clean water
    role: supply
    measurement: Water
    field: litres
    tags: { Container: CleanWaterTank }
"""

BARE = "name: BareHab\n"


class TestProfileParsing:
    def test_specialised_config_is_read(self, habitat):
        p = habitat(FULL_HABITAT)
        assert p.aggregate_tag_values == ("gridsupply", "habitat")
        assert p.noise_floor("Water", "litres") == 1.0
        assert p.electrical["phase_tag"] == "Phase"
        assert p.stock_measurements == ("Water",)
        assert p.stock_role("Water", {"Container": "CleanWaterTank"})["role"] == "supply"

    def test_a_bare_habitat_declares_none(self, habitat):
        p = habitat(BARE)
        assert p.aggregate_tag_values == ()
        assert p.noise_floor("Water", "litres") is None
        assert p.electrical == {}
        assert p.stock_measurements == ()


class TestAnalysisReadsTheProfile:
    def test_deadband_comes_from_the_profile(self, habitat):
        from app.telemetry import instruments

        habitat(FULL_HABITAT)
        assert instruments.deadband_for("Water", "litres") == (1.0, "measured")
        habitat(BARE)
        assert instruments.deadband_for("Water", "litres") == (0.0, "unknown")

    def test_rollup_tags_come_from_the_profile(self, habitat):
        from app.telemetry import aggregation

        habitat(FULL_HABITAT)
        assert aggregation._is_aggregate({"Connection": "GridSupply"})  # declared
        assert aggregation._is_aggregate({"Phase": "Total"})  # universal
        assert not aggregation._is_aggregate({"Phase": "1"})
        habitat(BARE)
        assert not aggregation._is_aggregate({"Connection": "GridSupply"})  # not declared


class TestToolSetFollowsTheHabitat:
    def test_tanks_and_phases_offered_only_when_declared(self, habitat):
        from app.tools import registry

        habitat(FULL_HABITAT)
        names = {s["name"] for s in registry.schemas()}
        assert {"get_tank_flow", "get_latest_all_phases"} <= names

        habitat(BARE)
        names = {s["name"] for s in registry.schemas()}
        assert "get_tank_flow" not in names
        assert "get_latest_all_phases" not in names
        # the neutral core is always there
        assert {"get_latest", "summarize", "get_consumption"} <= names


class TestStockRoles:
    """Clean/grey water is a universal habitat concern, expressed generically.

    ATLAS has no notion of "clean water" in its source — a habitat declares a
    stock and its role, and the tank analysis then names the right movement.
    """

    def test_a_supply_stock_names_the_fall_as_consumption(self, habitat):
        from app.telemetry import tanks

        habitat(FULL_HABITAT)
        note = tanks._reading_note("Water", {"Container": "CleanWaterTank"})
        assert "SUPPLY" in note and "CONSUMED" in note

    def test_a_waste_stock_names_the_rise_as_production(self, habitat):
        from app.telemetry import tanks

        habitat(
            """
name: WasteHab
stocks:
  - key: grey
    label: Grey water
    role: waste
    measurement: Water
    field: litres
    tags: { Container: GreyWaterTank }
"""
        )
        note = tanks._reading_note("Water", {"Container": "GreyWaterTank"})
        assert "WASTE" in note and "PRODUCED" in note

    def test_an_undeclared_tank_refuses_to_guess_which_it_is(self, habitat):
        from app.telemetry import tanks

        habitat(BARE)
        note = tanks._reading_note("Water", {"Container": "Unknown"})
        assert "has not declared" in note

    def test_the_most_specific_declaration_wins(self, habitat):
        # Two tanks in one measurement: the query's tags decide which is meant.
        p = habitat(
            """
name: TwoTanks
stocks:
  - key: clean
    label: Clean water
    role: supply
    measurement: Water
    field: litres
    tags: { Container: CleanWaterTank }
  - key: grey
    label: Grey water
    role: waste
    measurement: Water
    field: litres
    tags: { Container: GreyWaterTank }
"""
        )
        assert p.stock_role("Water", {"Container": "GreyWaterTank"})["key"] == "grey"
        assert p.stock_role("Water", {"Container": "CleanWaterTank"})["key"] == "clean"


class TestDashboardIsHabitatAgnostic:
    """No habitat's charts, rooms, or legends are baked into the source."""

    def test_the_source_declares_no_panels_of_its_own(self, habitat):
        from app.services import dashboard as dash

        # A habitat with no database reachable and no declared panels derives
        # nothing — there is no built-in catalogue to fall back on.
        habitat(BARE)
        assert dash.profile().dashboard_panels == ()

    def test_non_rooms_and_legend_prefixes_come_from_the_profile(self, habitat):
        from app.services import dashboard as dash

        habitat(
            """
name: PrefixHab
non_room_locations: [Outside, Rover]
tag_label_prefixes: { Bay: "Bay " }
"""
        )
        assert dash._not_a_room() == {"Outside", "Rover"}
        assert dash._label_for({"Bay": "3"}, "Bay") == ("Bay 3", "3")
