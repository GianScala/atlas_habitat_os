"""The habitat profile — mission-specific facts in config, not code.

These guard that a habitat is described by its YAML profile: swap the file and
the zone names and units change, with no source edit. The suite's own reference
habitat is covered by test_units and the zones used throughout.
"""

from app.habitat import profile, reset
from app.habitat.profile import HabitatProfile, _load


def _write(tmp_path, text: str):
    path = tmp_path / "habitat.yaml"
    path.write_text(text, encoding="utf-8")
    return path


class TestProfileLoading:
    def test_a_missions_profile_defines_its_own_world(self, tmp_path):
        path = _write(
            tmp_path,
            """
name: MarsSim
location_tag_keys: [Module, Host]
internal_prefixes: [sys_]
zone_names:
  Mod1: Living Quarters
  Mod2: Greenhouse
non_summable_fields: [voltage]
units:
  Temperature:
    value: K
""",
        )
        p = _load(path)
        assert p.name == "MarsSim"
        assert p.location_tag_keys == ("Module", "Host")
        assert p.zone_names["Mod2"] == "Greenhouse"
        assert p.unit_for("Temperature", "value") == ("K", "known")
        assert p.is_internal("sys_load")
        assert not p.is_internal("Temperature")

    def test_unknown_units_are_never_guessed(self, tmp_path):
        p = _load(_write(tmp_path, "name: Bare\n"))
        assert p.unit_for("Temperature", "value") == ("", "unknown")

    def test_a_missing_file_degrades_rather_than_crashes(self, tmp_path):
        p = _load(tmp_path / "nope.yaml")
        assert isinstance(p, HabitatProfile)
        assert p.name == "habitat"
        # Still has sane location-tag defaults so per-place queries can work.
        assert "Location" in p.location_tag_keys

    def test_a_garbage_file_degrades_rather_than_crashes(self, tmp_path):
        p = _load(_write(tmp_path, "- just\n- a\n- list\n"))
        assert p.name == "habitat"


class TestTheSuitesHabitat:
    def test_the_pinned_profile_is_the_reference_station(self):
        # conftest points HABITAT_CONFIG at tests/fixtures/reference_habitat.yaml
        # so the suite never depends on a shipped example or a developer's .env.
        reset()
        try:
            assert profile().name == "Reference Station"
            assert profile().unit_for("Water", "litres") == ("L", "known")
        finally:
            reset()
