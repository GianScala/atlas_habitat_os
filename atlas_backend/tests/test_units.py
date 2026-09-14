"""Units — never guessed, and never silently dropped."""

from app.telemetry import units


class TestUnitLookup:
    def test_a_known_field_reports_its_unit(self):
        assert units.unit_for("Water", "litres") == ("L", "known")

    def test_an_unlisted_field_is_unknown_not_blank(self):
        # The caller has to be able to tell "no dimension" from "we don't
        # know", because the honest answer differs: a power factor really is
        # dimensionless, an unlisted field is a number we cannot caption.
        assert units.unit_for("HCHO", "value") == ("", "unknown")
        assert units.unit_for("Electricity", "powerFactor") == ("", "known")

    def test_an_unknown_measurement_is_unknown(self):
        assert units.unit_for("Tachyons", "value") == ("", "unknown")


class TestEnergyTotaliser:
    """The one unit established by measurement rather than by a dashboard.

    Checked against the same meter's power_active, which is known to be watts:
    over 24 h the totaliser rose 51.91 while mean power was 2.159 kW, wanting
    51.82. Agreement to 0.2% across a full day of varying load rules out Wh,
    which would have been out by a factor of 1000.
    """

    def test_the_habitat_totaliser_is_kwh(self):
        assert units.unit_for("Energy", "total_forward_active_energy") == (
            "kWh",
            "known",
        )

    def test_it_agrees_with_the_electricity_meter_spelling(self):
        # Two measurements, two naming conventions, one physical quantity. If
        # these ever disagree, one of them is wrong.
        snake, _ = units.unit_for("Energy", "total_forward_active_energy")
        camel, _ = units.unit_for("Electricity", "totalForwardActiveEnergy")

        assert snake == camel

    def test_power_and_its_totaliser_are_not_the_same_dimension(self):
        # A rate is not an amount. Charting the totaliser's DIFFERENCE is what
        # makes the panel an energy-per-interval reading rather than a level.
        power, _ = units.unit_for("Energy", "power_active")
        energy, _ = units.unit_for("Energy", "total_forward_active_energy")

        assert power == "W" and energy == "kWh"
