"""Tank flow — where netting two directions destroys the answer.

The failure these guard against produced a real wrong answer: asked for three
days of water consumption, ATLAS reported that the clean tank had gone UP by
367 L and that consumption could not be computed. Both halves came from the
same mistake — treating a stock's net change as though it described a flow.
"""

import pytest

from app.core.errors import QueryError
from app.telemetry import influxql as ql
from app.telemetry import instruments, tanks


def levels(*pairs: tuple[str, float]) -> tuple[list, list]:
    """(columns, values) as InfluxDB returns a bucketed mean series."""
    return ["time", "mean"], [[moment, value] for moment, value in pairs]


def hourly(start_hour: int, *values: float, day: int = 18) -> tuple[list, list]:
    """A run of hourly buckets, for readability in the cases below."""
    return levels(
        *(
            (f"2026-08-{day:02d}T{start_hour + i:02d}:00:00Z", value)
            for i, value in enumerate(values)
        )
    )


def decompose(columns, values, deadband=0.0, group_by="day"):
    return tanks._decompose({}, columns, values, deadband, group_by)


class TestTheNettingBug:
    """The headline case, in the shape the real data had it."""

    def test_a_refill_and_a_drawdown_are_reported_separately(self):
        # Refilled 800 L, then drunk down 430 L. Net is +370, which is neither.
        columns, values = hourly(0, 930.0, 1730.0, 1600.0, 1450.0, 1300.0)
        entry = decompose(columns, values)

        assert entry["total_rose"] == 800.0
        assert entry["total_fell"] == 430.0

    def test_the_net_is_reported_but_never_as_either_one(self):
        columns, values = hourly(0, 930.0, 1730.0, 1600.0, 1450.0, 1300.0)
        entry = decompose(columns, values)

        # It is present, because it is a true fact about the tank...
        assert entry["net_from_levels"] == 370.0
        # ...and it equals neither of the two quantities anyone asks for.
        assert entry["net_from_levels"] != entry["total_fell"]
        assert entry["net_from_levels"] != entry["total_rose"]

    def test_a_tank_that_ends_where_it_started_still_moved(self):
        # The grey tank case: filled and emptied, net zero, and about 120 L of
        # real flow that last-minus-first reports as nothing at all.
        columns, values = hourly(0, 100.0, 160.0, 100.0, 160.0, 100.0)
        entry = decompose(columns, values)

        assert entry["net_from_levels"] == 0.0
        assert entry["total_rose"] == 120.0
        assert entry["total_fell"] == 120.0


class TestLeadIn:
    def test_the_first_bucket_is_the_reference_not_a_measurement(self):
        # Three buckets, two changes. The first has nothing before it to be a
        # change from, and inventing one is not an option.
        columns, values = hourly(0, 100.0, 110.0, 105.0)
        entry = decompose(columns, values)

        assert entry["total_rose"] == 10.0
        assert entry["total_fell"] == 5.0
        assert entry["opening_level"] == 100.0

    def test_a_series_with_nothing_to_compare_is_dropped(self):
        assert decompose(*hourly(0, 100.0)) is None
        assert decompose(["time", "mean"], []) is None

    def test_empty_buckets_are_skipped_not_treated_as_zero(self):
        columns = ["time", "mean"]
        values = [
            ["2026-08-18T00:00:00Z", 100.0],
            ["2026-08-18T01:00:00Z", None],
            ["2026-08-18T02:00:00Z", 90.0],
        ]
        entry = decompose(columns, values)

        # A gap is not a reading of zero. The next bucket that reports is a
        # change from the last one that did.
        assert entry["total_fell"] == 10.0
        assert entry["analysis_buckets"] == 2


class TestDeadband:
    def test_wobble_below_the_floor_is_not_consumption(self):
        # A motionless tank, dithering. Without a deadband the falls are kept
        # and the rises discarded, so it reports use that never happened.
        columns, values = hourly(0, 100.0, 100.4, 100.0, 100.3, 99.8, 100.2)

        noisy = decompose(columns, values, deadband=0.0)
        clean = decompose(columns, values, deadband=1.0)

        assert noisy["total_fell"] > 0
        assert clean["total_fell"] == 0.0
        assert clean["total_rose"] == 0.0

    def test_a_drain_slower_than_the_deadband_is_still_counted(self):
        # The reason the threshold is held against a reference rather than
        # applied per step: 0.4 L an hour never clears 1 L in one bucket, but
        # it is a real 2.4 L drain and must not vanish.
        columns, values = hourly(0, 100.0, 99.6, 99.2, 98.8, 98.4, 98.0, 97.6)
        entry = decompose(columns, values, deadband=1.0)

        assert entry["total_fell"] >= 2.0
        assert entry["total_rose"] == 0.0

    def test_the_deadband_does_not_ratchet_across_a_refill(self):
        columns, values = hourly(0, 100.0, 99.5, 400.0)
        entry = decompose(columns, values, deadband=1.0)

        assert entry["total_rose"] == 300.0

    def test_the_unreconciled_gap_is_the_deadbands_tail_and_is_bounded(self):
        # Use still sitting below the threshold when the window ends is not
        # yet attributed. That is a real undercount, so it is published rather
        # than hidden — and it can never exceed one deadband.
        columns, values = hourly(0, 100.0, 99.6, 99.4)
        entry = decompose(columns, values, deadband=1.0)

        assert entry["total_fell"] == 0.0
        assert entry["net_from_levels"] == -0.6
        assert abs(entry["unreconciled"]) <= 1.0

    def test_movements_reconcile_exactly_when_nothing_is_suppressed(self):
        columns, values = hourly(0, 100.0, 130.0, 90.0, 140.0)
        entry = decompose(columns, values, deadband=0.0)

        assert entry["net_from_moves"] == entry["net_from_levels"]
        assert entry["unreconciled"] == 0.0


class TestPeriods:
    def test_movements_land_in_the_period_they_happened_in(self):
        columns, values = levels(
            ("2026-08-18T22:00:00Z", 100.0),
            ("2026-08-18T23:00:00Z", 90.0),
            ("2026-08-19T00:00:00Z", 70.0),
            ("2026-08-19T01:00:00Z", 120.0),
        )
        entry = decompose(columns, values, group_by="day")
        by_day = {p["period_start"][:10]: p for p in entry["per_period"]}

        assert by_day["2026-08-18"]["fell"] == 10.0
        assert by_day["2026-08-19"]["fell"] == 20.0
        assert by_day["2026-08-19"]["rose"] == 50.0

    def test_a_quiet_period_appears_as_zeroes_rather_than_vanishing(self):
        columns, values = levels(
            ("2026-08-18T22:00:00Z", 100.0),
            ("2026-08-19T00:00:00Z", 100.0),
            ("2026-08-20T00:00:00Z", 80.0),
        )
        entry = decompose(columns, values, group_by="day")
        days = [p["period_start"][:10] for p in entry["per_period"]]

        assert days == ["2026-08-19", "2026-08-20"]
        assert entry["per_period"][0] == {
            "period_start": "2026-08-19T00:00:00Z",
            "fell": 0.0,
            "rose": 0.0,
            "net": 0.0,
        }

    def test_hourly_and_weekly_periods_truncate_correctly(self):
        assert tanks._period_start("2026-08-19T13:45:00Z", "hour") == (
            "2026-08-19T13:00:00Z"
        )
        assert tanks._period_start("2026-08-19T13:45:00Z", "day") == (
            "2026-08-19T00:00:00Z"
        )
        # 2026-08-19 is a Wednesday; its ISO week starts on the Monday.
        assert tanks._period_start("2026-08-19T13:45:00Z", "week") == (
            "2026-08-17T00:00:00Z"
        )

    def test_an_unknown_group_by_is_refused_before_querying(self):
        with pytest.raises(QueryError):
            tanks.get_tank_flow("Water", group_by="fortnight")


class TestBasisDays:
    """A per-day average divides by the window, not by the buckets it spans."""

    def _series(self, opening: str, closing: str) -> list[dict]:
        return [{"opening_time": opening, "closing_time": closing}]

    def test_a_rolling_window_divides_by_its_own_length(self):
        # Three days that touch four UTC days. Dividing by four would
        # understate every daily figure by a quarter.
        series = self._series("2026-08-18T09:00:00Z", "2026-08-21T09:00:00Z")
        assert tanks._basis_days(series, 3.0)["days"] == 3.0

    def test_an_open_ended_window_falls_back_to_what_the_data_spans(self):
        series = self._series("2026-08-18T00:00:00Z", "2026-08-20T00:00:00Z")
        basis = tanks._basis_days(series, None)

        assert basis["days"] == 2.0
        assert "readings actually span" in basis["explanation"]

    def test_a_gappy_record_is_flagged_rather_than_averaged_over(self):
        series = self._series("2026-08-20T00:00:00Z", "2026-08-21T00:00:00Z")
        basis = tanks._basis_days(series, 7.0)

        assert basis["days"] == 7.0
        assert "coverage_warning" in basis
        assert "incomplete" in basis["coverage_warning"]

    def test_full_coverage_raises_no_warning(self):
        series = self._series("2026-08-18T00:00:00Z", "2026-08-21T00:00:00Z")
        assert "coverage_warning" not in tanks._basis_days(series, 3.0)

    def test_rates_divide_the_totals_by_the_basis(self):
        entry = {"total_fell": 430.0, "total_rose": 800.0}
        tanks._attach_rates(entry, 3.0)

        assert entry["fell_per_day"] == pytest.approx(143.3333, abs=1e-3)
        assert entry["rose_per_day"] == pytest.approx(266.6667, abs=1e-3)


class TestSummary:
    """Four near-identically named numbers are easy to transpose in prose."""

    def _entry(self) -> dict:
        entry = {
            "tags": {"Container": "GreyWaterTank"},
            "total_fell": 180.5,
            "total_rose": 174.4,
            "opening_level": 97.0,
            "closing_level": 91.0,
        }
        tanks._attach_rates(entry, 3.0)
        tanks._attach_summary(entry, "L", "known", 3.0)
        return entry

    def test_it_states_both_directions_with_the_right_number_on_each(self):
        summary = self._entry()["summary"]

        assert "FELL by 180.5 L" in summary
        assert "ROSE by 174.4 L" in summary

    def test_it_names_the_series_so_two_tanks_cannot_be_confused(self):
        assert "GreyWaterTank" in self._entry()["summary"]

    def test_an_unknown_unit_is_left_off_rather_than_invented(self):
        entry = {
            "tags": {},
            "total_fell": 10.0,
            "total_rose": 4.0,
            "opening_level": 50.0,
            "closing_level": 44.0,
        }
        tanks._attach_summary(entry, "", "unknown", 1.0)

        assert "FELL by 10 and ROSE by 4" in entry["summary"]


class TestNoiseFloors:
    def test_a_measured_instrument_reports_its_floor_and_its_provenance(self):
        assert instruments.deadband_for("Water", "litres") == (1.0, "measured")

    def test_an_unknown_instrument_is_never_given_a_plausible_default(self):
        # Guessing either invents consumption or erases it, and the answer
        # gives no way to tell which happened.
        assert instruments.deadband_for("Battery", "volts") == (0.0, "unknown")

    def test_an_override_is_taken_but_labelled_as_the_callers(self):
        assert instruments.resolve_deadband("Water", "litres", 5.0) == (5.0, "caller")

    def test_a_negative_deadband_is_refused(self):
        with pytest.raises(ValueError):
            instruments.resolve_deadband("Water", "litres", -1.0)

    def test_the_dashboard_and_the_chat_tools_share_one_floor(self):
        # A chart and an answer built from the same gauge have to agree. The
        # habitat's water panels ask for `deadband: auto`, which resolves to the
        # same measured floor the chat tools difference that gauge against.
        from app.services import dashboard

        floor = instruments.deadband_for("Water", "litres")[0]
        charted = [
            panel
            for panel in dashboard.catalogue()
            if panel.measurement == "Water" and panel.deadband
        ]
        assert charted, "the habitat declares no deadbanded water panel"
        for panel in charted:
            assert panel.deadband == floor, panel.id


class TestResolution:
    def test_three_days_are_differenced_finely_enough_to_keep_a_refill(self):
        # At 180 minutes an 800 L delivery and the level before it land in one
        # bucket and half the delivery is averaged away.
        assert ql.resolution_minutes(3 * 1440) <= 60

    def test_never_finer_than_the_gauges_can_support(self):
        assert ql.resolution_minutes(60) == ql.MIN_RESOLUTION

    def test_a_long_window_steps_up_rather_than_fetching_forever(self):
        assert ql.resolution_minutes(365 * 1440) > ql.resolution_minutes(3 * 1440)

    def test_an_open_ended_window_uses_the_finest_trustworthy_grain(self):
        assert ql.resolution_minutes(None) == ql.MIN_RESOLUTION
