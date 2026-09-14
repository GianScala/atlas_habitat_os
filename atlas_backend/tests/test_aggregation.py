"""Consumption arithmetic — where a plausible-looking wrong number comes from.

The failure these guard against is subtle: subtracting one meter's reading
from another's produces a large number that still looks monotonic, so nothing
downstream notices it is fiction.
"""

from app.telemetry.aggregation import (
    _attach_total,
    _attach_whole_window,
    _is_aggregate,
    _per_series_periods,
    _period_basis,
)


def series_result(*series: tuple[dict, list[tuple]]) -> dict:
    """Build a parsed influxql result of first/last rows, as InfluxDB returns."""
    return {
        "series": [
            {
                "name": "Electricity",
                "tags": tags,
                "columns": ["time", "first", "last"],
                "values": [list(row) for row in rows],
            }
            for tags, rows in series
        ]
    }


def with_extremes(*series: tuple[dict, list[tuple]]) -> dict:
    """The same, carrying the min/max the cumulative check reads."""
    return {
        "series": [
            {
                "name": "Energy",
                "tags": tags,
                "columns": ["time", "first", "last", "min", "max"],
                "values": [list(row) for row in rows],
            }
            for tags, rows in series
        ]
    }


class TestAggregateDetection:
    def test_spots_rollup_tag_values(self):
        assert _is_aggregate({"Phase": "Total"})
        assert _is_aggregate({"Connection": "GridSupply"})
        assert _is_aggregate({"Meter": "habitat"})

    def test_leaves_real_meters_alone(self):
        assert not _is_aggregate({"Phase": "1"})
        assert not _is_aggregate({"Location": "Container3"})

    def test_does_not_guess_at_room_groups(self):
        # OpsDormKitch groups three rooms but is not a whole-system rollup.
        # Wrongly excluding a real meter understates a total just as badly as
        # double-counting overstates it.
        assert not _is_aggregate({"Location": "OpsDormKitch"})


class TestPerSeriesPeriods:
    def test_subtracts_each_meter_separately(self):
        result = series_result(
            ({"Phase": "1"}, [("2026-08-18T00:00:00Z", 100.0, 110.0)]),
            ({"Phase": "2"}, [("2026-08-18T00:00:00Z", 500.0, 515.0)]),
        )
        series = _per_series_periods(result)

        assert len(series) == 2
        assert series[0]["per_period"][0]["delta"] == 10.0
        assert series[1]["per_period"][0]["delta"] == 15.0
        # Never 515 - 100: that would be subtracting one meter from another.

    def test_marks_a_falling_series_as_not_cumulative(self):
        result = series_result(
            ({"Phase": "1"}, [
                ("2026-08-18T00:00:00Z", 100.0, 110.0),
                ("2026-08-19T00:00:00Z", 110.0, 90.0),  # meter reset
            ]),
        )
        series = _per_series_periods(result)

        assert series[0]["cumulative"] is False
        assert series[0]["periods_falling"] == 1

    def test_spots_a_meter_that_dipped_inside_a_bucket(self):
        # Endpoint arithmetic alone cannot see this: the day starts at 100 and
        # ends at 130, so its delta is a healthy +30, but the meter went down
        # to 40 somewhere in between. That is a reset, and the "consumption"
        # built on it would be fiction.
        result = with_extremes(
            ({"Phase": "1"}, [("2026-08-18T00:00:00Z", 100.0, 130.0, 40.0, 130.0)]),
        )
        series = _per_series_periods(result)

        assert series[0]["per_period"][0]["delta"] == 30.0
        assert series[0]["cumulative"] is False
        assert series[0]["periods_dipping"] == 1

    def test_a_genuinely_climbing_meter_is_left_alone(self):
        result = with_extremes(
            ({"Phase": "1"}, [("2026-08-18T00:00:00Z", 100.0, 130.0, 100.0, 130.0)]),
        )
        series = _per_series_periods(result)

        assert series[0]["cumulative"] is True
        assert series[0]["periods_dipping"] == 0

    def test_skips_periods_with_missing_endpoints(self):
        result = series_result(
            ({"Phase": "1"}, [
                ("2026-08-18T00:00:00Z", None, 110.0),
                ("2026-08-19T00:00:00Z", 110.0, 130.0),
            ]),
        )
        series = _per_series_periods(result)

        assert len(series[0]["per_period"]) == 1
        assert series[0]["per_period"][0]["delta"] == 20.0

    def test_drops_series_with_nothing_usable(self):
        result = series_result(({"Phase": "3"}, [("2026-08-18T00:00:00Z", None, None)]))
        assert _per_series_periods(result) == []

    def test_keeps_both_endpoints_so_the_arithmetic_is_checkable(self):
        result = series_result(({"Phase": "1"}, [("2026-08-18T00:00:00Z", 100.0, 110.0)]))
        period = _per_series_periods(result)[0]["per_period"][0]

        assert period["first"] == 100.0
        assert period["last"] == 110.0


class TestWholeWindow:
    def test_matches_endpoints_to_their_own_series(self):
        series = _per_series_periods(
            series_result(
                ({"Phase": "1"}, [("2026-08-18T00:00:00Z", 100.0, 110.0)]),
                ({"Phase": "2"}, [("2026-08-18T00:00:00Z", 500.0, 515.0)]),
            )
        )
        overall = series_result(
            ({"Phase": "1"}, [("2026-08-18T00:00:00Z", 100.0, 130.0)]),
            ({"Phase": "2"}, [("2026-08-18T00:00:00Z", 500.0, 540.0)]),
        )

        _attach_whole_window(series, overall)

        assert series[0]["whole_window"]["delta"] == 30.0
        assert series[1]["whole_window"]["delta"] == 40.0

    def test_absent_endpoints_leave_none(self):
        series = _per_series_periods(
            series_result(({"Phase": "1"}, [("2026-08-18T00:00:00Z", 100.0, 110.0)]))
        )
        _attach_whole_window(series, {"series": []})
        assert series[0]["whole_window"] is None


class TestTotal:
    def _summed(self, series: list[dict]) -> dict:
        out: dict = {"data": {}}
        real = [s for s in series if not s["is_aggregate"]]
        aggregates = [s for s in series if s["is_aggregate"]]
        _attach_total(out, series, real, aggregates, {"2026-08-18T00:00:00Z"}, "energy")
        return out

    def test_sums_real_meters(self):
        series = _per_series_periods(
            series_result(
                ({"Phase": "1"}, [("2026-08-18T00:00:00Z", 100.0, 110.0)]),
                ({"Phase": "2"}, [("2026-08-18T00:00:00Z", 500.0, 515.0)]),
            )
        )
        _attach_whole_window(series, {"series": []})

        out = self._summed(series)
        assert out["data"]["total_all_series"] == 25.0

    def test_excludes_a_rollup_series_from_the_total(self):
        series = _per_series_periods(
            series_result(
                ({"Phase": "1"}, [("2026-08-18T00:00:00Z", 100.0, 110.0)]),
                ({"Phase": "2"}, [("2026-08-18T00:00:00Z", 500.0, 515.0)]),
                ({"Phase": "Total"}, [("2026-08-18T00:00:00Z", 600.0, 625.0)]),
            )
        )
        _attach_whole_window(series, {"series": []})

        out = self._summed(series)

        # 10 + 15, not 10 + 15 + 25.
        assert out["data"]["total_all_series"] == 25.0
        assert "aggregate_warning" in out
        assert out["data"]["aggregate_series"][0]["delta"] == 25.0

    def test_falls_back_to_rollups_when_they_are_all_we_have(self):
        series = _per_series_periods(
            series_result(({"Phase": "Total"}, [("2026-08-18T00:00:00Z", 600.0, 625.0)]))
        )
        _attach_whole_window(series, {"series": []})

        out = self._summed(series)
        assert out["data"]["total_all_series"] == 25.0

    def _two_days(self) -> list[dict]:
        series = _per_series_periods(
            series_result(
                ({"Phase": "1"}, [
                    ("2026-08-18T00:00:00Z", 100.0, 110.0),
                    ("2026-08-19T00:00:00Z", 110.0, 130.0),
                ]),
            )
        )
        _attach_whole_window(series, {"series": []})
        return series

    def test_average_divides_by_the_window_not_the_buckets_touched(self):
        # The bug this replaces: a 3-day rolling window starting mid-morning
        # touches FOUR UTC-midnight buckets, so dividing by the bucket count
        # reported three days of use as a four-day average — a quarter low,
        # and entirely plausible-looking.
        series = self._two_days()
        out: dict = {"data": {}}
        touched = {f"2026-08-{d}T00:00:00Z" for d in (18, 19, 20, 21)}

        _attach_total(
            out, series, series, [], touched, "energy",
            _period_basis(days=3, start=None, end=None, bucket=1440,
                          period_starts=touched),
        )

        assert out["data"]["total_all_series"] == 30.0
        assert out["data"]["periods_basis"] == 3.0
        assert out["data"]["average_per_period"] == 10.0  # not 7.5

    def test_an_open_window_falls_back_to_the_periods_with_readings(self):
        series = self._two_days()
        out: dict = {"data": {}}
        periods = {"2026-08-18T00:00:00Z", "2026-08-19T00:00:00Z"}

        _attach_total(
            out, series, series, [], periods, "energy",
            _period_basis(days=None, start=None, end=None, bucket=1440,
                          period_starts=periods),
        )

        assert out["data"]["average_per_period"] == 15.0

    def test_hourly_buckets_divide_by_hours_not_days(self):
        basis, _ = _period_basis(
            days=2, start=None, end=None, bucket=60, period_starts=set()
        )
        assert basis == 48.0
