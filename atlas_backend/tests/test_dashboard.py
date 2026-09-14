"""The panel catalogue, and the contract between it and the wire.

The catalogue is no longer a constant in the source — it comes from the habitat
profile (conftest pins the suite to its own reference habitat). These assert the
properties any catalogue must have, and the charts that habitat declares.
"""

import pytest

from app.schemas.dashboard import Panel as PanelSchema
from app.services import dashboard as dash
from app.telemetry import timeseries as ts


@pytest.fixture(scope="module")
def panels() -> tuple:
    """The habitat's declared catalogue, unfiltered by what a database holds."""
    return dash.catalogue()


@pytest.fixture(scope="module")
def by_id(panels) -> dict:
    return {panel.id: panel for panel in panels}


class TestPanelPayload:
    def test_every_field_the_service_emits_survives_the_response_model(self, panels):
        # FastAPI drops keys the response model does not declare, silently and
        # without failing a single test that stops at the service layer. That
        # is how `cumulative` reached the browser as absent on its first
        # outing: built correctly, serialised away.
        panel = panels[0]
        emitted = set(dash._failed_panel(panel, "no datasource"))

        assert emitted <= set(PanelSchema.model_fields)

    def test_a_failed_panel_still_answers_every_question_a_card_asks(self, by_id):
        # A panel that could not load still has to render as a captioned card
        # carrying its error, not as a hole.
        failed = dash._failed_panel(by_id["clean_water_level"], "down")

        assert PanelSchema(**failed).error == "down"


class TestCatalogue:
    def test_panel_ids_are_unique(self, panels):
        ids = [panel.id for panel in panels]

        assert len(ids) == len(set(ids))

    def test_every_panel_declares_a_known_chart_and_mode(self, panels):
        for panel in panels:
            assert panel.chart in {"line", "area", "bar"}, panel.id
            assert panel.mode in ts.MODES, panel.id

    def test_only_change_panels_accumulate(self, panels):
        # A running total of a temperature is a number with no referent, and
        # timeseries.series refuses to build one. Catch it in the catalogue
        # rather than as a panel that fails at request time.
        for panel in panels:
            if panel.cumulative:
                assert panel.mode != ts.MEAN, panel.id

    def test_a_panel_with_no_known_unit_says_why(self, panels):
        # The card falls back to a bare "no unit" chip. That is honest only if
        # it can explain itself on hover; an unexplained one just looks broken,
        # which is how the habitat energy panel read for as long as it had one.
        from app.telemetry import units

        for panel in panels:
            _, source = units.unit_for(panel.measurement, panel.field)
            if source == "unknown":
                assert panel.unit_note, panel.id

    def test_a_deadband_is_only_claimed_where_one_was_measured(self, panels):
        # A panel must not invent a noise floor the instrument table does not
        # have; the chat tools difference these same gauges against that table
        # and the two have to agree.
        from app.telemetry import instruments

        for panel in panels:
            if not panel.deadband:
                continue
            floor, source = instruments.deadband_for(panel.measurement, panel.field)
            assert source == "measured", panel.id
            assert panel.deadband == floor, panel.id


class TestCleanWaterPanels:
    """The consumption pair, which has to stay reconcilable with the level."""

    def test_the_running_total_reads_the_same_gauge_as_the_bars(self, by_id):
        bars = by_id["clean_water_consumption"]
        total = by_id["clean_water_consumption_total"]

        assert (total.measurement, total.field, total.tags) == (
            bars.measurement,
            bars.field,
            bars.tags,
        )
        assert (total.mode, total.deadband) == (bars.mode, bars.deadband)
        assert total.cumulative and not bars.cumulative

    def test_consumption_is_drawn_down_not_netted(self, by_id):
        # A refill is not negative consumption. The clean tank is a supply
        # tank, so a fall is use and a rise is a delivery.
        assert by_id["clean_water_consumption"].mode == ts.DRAWDOWN

    def test_the_grey_tank_keeps_its_sign(self, by_id):
        # The waste tank's chart is about arriving and emptying, both of which
        # a reader needs to see; one-siding it would hide half the story.
        assert by_id["grey_water_change"].mode == ts.DELTA
