"""Chart aggregation — where a refill could be mistaken for negative use."""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.errors import QueryError
from app.telemetry import timeseries as ts


class TestRanges:
    def test_every_range_has_a_label(self):
        assert set(ts.RANGES) == set(ts.RANGE_LABELS)

    def test_buckets_give_a_sane_number_of_points(self):
        for key, (minutes, bucket) in ts.RANGES.items():
            points = minutes / bucket
            assert 10 <= points <= 200, f"{key} would plot {points:.0f} points"

    def test_longer_ranges_never_use_smaller_buckets(self):
        ordered = list(ts.RANGES.values())
        for (earlier_window, earlier_bucket), (later_window, later_bucket) in zip(
            ordered, ordered[1:], strict=False
        ):
            assert later_window > earlier_window
            assert later_bucket >= earlier_bucket

    def test_unknown_range_is_refused(self):
        with pytest.raises(QueryError):
            ts.resolve_range("42y")

    def test_the_refusal_names_the_windows_that_do_exist(self):
        # The preset list is version-specific — this one dropped 15 minutes and
        # gained 5 hours — so a browser remembering an old choice asks for a
        # window that is gone. The reply has to say what to ask for instead.
        with pytest.raises(QueryError) as refused:
            ts.resolve_range("15m")

        assert "24h" in refused.value.message
        assert ts.CUSTOM_PREFIX in refused.value.message


class TestCustomWindow:
    """A window the reader picked the start of, rather than the length of."""

    def _key(self, **ago) -> str:
        start = datetime.now(UTC) - timedelta(**ago)
        return f"{ts.CUSTOM_PREFIX}{start.isoformat()}"

    def test_the_span_is_measured_from_the_start_to_now(self):
        window = ts.resolve_window(self._key(hours=5))

        assert 299 <= window.minutes <= 301

    def test_the_key_comes_back_exactly_as_it_went_in(self):
        # The browser compares the payload's range against the filter it has
        # selected, to know whether the charts on screen are still the answer
        # to the current question. Normalising the key here would make every
        # custom window read as permanently out of date.
        key = f"{ts.CUSTOM_PREFIX}2026-08-20T14:00:00.000Z"

        assert ts.resolve_window(key).key == key

    def test_the_start_is_kept_as_an_instant(self):
        # Not as a distance back from now. A rolling offset would drift between
        # the twelve panels of one page and again on every refetch.
        window = ts.resolve_window(f"{ts.CUSTOM_PREFIX}2026-08-20T14:00:00Z")

        assert window.start is not None
        assert window.start.startswith("2026-08-20T14:00:00")

    def test_a_naive_instant_is_read_as_utc(self):
        assert ts.resolve_window(f"{ts.CUSTOM_PREFIX}2026-08-20T14:00:00").start

    def test_a_start_in_the_future_is_refused(self):
        with pytest.raises(QueryError) as refused:
            ts.resolve_window(f"{ts.CUSTOM_PREFIX}2099-01-01T00:00:00Z")

        assert "future" in refused.value.message

    def test_a_start_too_recent_to_chart_is_refused(self):
        with pytest.raises(QueryError):
            ts.resolve_window(self._key(minutes=1))

    def test_a_start_beyond_the_ceiling_is_refused(self):
        with pytest.raises(QueryError):
            ts.resolve_window(self._key(days=ts.MAX_CUSTOM_MINUTES // 1440 + 1))

    def test_junk_is_refused_rather_than_escaped(self):
        for key in (f"{ts.CUSTOM_PREFIX}banana", ts.CUSTOM_PREFIX, f"{ts.CUSTOM_PREFIX}  "):
            with pytest.raises(QueryError):
                ts.resolve_window(key)

    def test_a_custom_span_draws_at_the_same_resolution_as_the_preset(self):
        # "Since five hours ago" and the 5h preset must not disagree about the
        # same afternoon by plotting it at two different bucket sizes.
        for key, (minutes, bucket) in ts.RANGES.items():
            assert ts._bucket_for(minutes) == bucket, key

    def test_every_allowed_span_plots_a_sane_number_of_points(self):
        for minutes in (5, 17, 90, 300, 1441, 10_080, ts.MAX_CUSTOM_MINUTES):
            points = minutes / ts._bucket_for(minutes)
            assert points <= 200, f"{minutes} min would plot {points:.0f} points"


class TestChange:
    def test_delta_is_signed(self):
        assert ts._change(100.0, 130.0, ts.DELTA) == 30.0
        assert ts._change(130.0, 100.0, ts.DELTA) == -30.0

    def test_drawdown_counts_a_falling_level_as_use(self):
        assert ts._change(1376.3, 1317.9, ts.DRAWDOWN) == 58.4

    def test_drawdown_treats_a_refill_as_zero_use(self):
        # A tank being refilled is not negative consumption. Letting it go
        # negative would cancel real use earlier in the window.
        assert ts._change(1000.0, 1500.0, ts.DRAWDOWN) == 0.0

    def test_fillup_counts_a_rising_level_as_arrival(self):
        # The waste-tank half: on a grey tank a rise is what the habitat
        # produced, and drawdown would report none of it.
        assert ts._change(100.0, 160.0, ts.FILLUP) == 60.0

    def test_fillup_treats_an_emptying_as_zero_arrival(self):
        assert ts._change(160.0, 100.0, ts.FILLUP) == 0.0

    def test_the_two_one_sided_modes_are_mirror_images(self):
        # Together they account for the whole movement, which is what makes
        # the reconciliation in tanks.py exact.
        for previous, current in ((100.0, 160.0), (160.0, 100.0), (100.0, 100.0)):
            fell = ts._change(previous, current, ts.DRAWDOWN)
            rose = ts._change(previous, current, ts.FILLUP)
            assert rose - fell == ts._change(previous, current, ts.DELTA)


class TestReadSeries:
    def test_points_carry_time_and_value(self):
        entry = ts._read_series(
            {"Location": "Atrium"},
            ["time", "mean"],
            [["2026-08-20T00:00:00Z", 21.0], ["2026-08-20T01:00:00Z", 22.0]],
            ts.MEAN,
        )

        assert entry["tags"] == {"Location": "Atrium"}
        assert entry["points"] == [
            {"t": "2026-08-20T00:00:00Z", "v": 21.0},
            {"t": "2026-08-20T01:00:00Z", "v": 22.0},
        ]

    def test_empty_buckets_are_dropped_not_zeroed(self):
        # Plotting a gap as zero would invent a reading of nothing.
        entry = ts._read_series(
            {},
            ["time", "mean"],
            [["2026-08-20T00:00:00Z", None], ["2026-08-20T01:00:00Z", 22.0]],
            ts.MEAN,
        )

        assert entry["points"] == [{"t": "2026-08-20T01:00:00Z", "v": 22.0}]


class TestChangeSeries:
    """A change is measured between buckets, never inside one."""

    def _read(self, rows, mode=ts.DELTA, deadband=0.0):
        return ts._read_series({}, ["time", "mean"], rows, mode, deadband)["points"]

    def test_a_bucket_is_the_change_since_the_one_before_it(self):
        points = self._read(
            [
                ["2026-08-20T00:00:00Z", 100.0],
                ["2026-08-20T00:01:00Z", 130.0],
                ["2026-08-20T00:02:00Z", 125.0],
            ]
        )

        # The lead bucket is spent establishing where the level started, so it
        # is not plotted — there is nothing before it to compare it against.
        assert points == [
            {"t": "2026-08-20T00:01:00Z", "v": 30.0},
            {"t": "2026-08-20T00:02:00Z", "v": -5.0},
        ]

    def test_one_reading_per_bucket_still_reports_its_change(self):
        # The regression this file exists for: differencing inside a bucket
        # made every single-reading bucket exactly zero, so a one-minute
        # resolution showed a tank in steady use as flat and unchanging.
        points = self._read(
            [
                ["2026-08-20T00:00:00Z", 1314.8],
                ["2026-08-20T00:01:00Z", 1314.4],
                ["2026-08-20T00:02:00Z", 1314.1],
            ],
            ts.DRAWDOWN,
        )

        assert points == [
            {"t": "2026-08-20T00:01:00Z", "v": 0.4},
            {"t": "2026-08-20T00:02:00Z", "v": 0.3},
        ]

    def test_the_buckets_sum_to_the_change_across_the_window(self):
        # Nothing may fall between two buckets and go unreported.
        rows = [
            ["2026-08-20T00:00:00Z", 10.0],
            ["2026-08-20T00:01:00Z", 12.0],
            ["2026-08-20T00:02:00Z", 19.0],
            ["2026-08-20T00:03:00Z", 20.5],
        ]

        assert sum(point["v"] for point in self._read(rows)) == 10.5

    def test_an_empty_bucket_is_skipped_rather_than_read_as_no_change(self):
        points = self._read(
            [
                ["2026-08-20T00:00:00Z", 100.0],
                ["2026-08-20T00:01:00Z", None],
                ["2026-08-20T00:02:00Z", 108.0],
            ]
        )

        assert points == [{"t": "2026-08-20T00:02:00Z", "v": 8.0}]

    def test_a_single_reading_yields_no_change_at_all(self):
        assert self._read([["2026-08-20T00:00:00Z", 100.0]]) == []


class TestDeadband:
    """A gauge that wobbles while the tank sits still must report no use.

    Without this, `drawdown` kept every downward wobble and discarded every
    upward one, so a clean water tank that ended an hour 1 L FULLER than it
    started was charted as having supplied 7.7 L.
    """

    def _read(self, levels, mode=ts.DRAWDOWN, deadband=1.0):
        rows = [[f"2026-08-20T00:{minute:02d}:00Z", v] for minute, v in enumerate(levels)]
        return ts._read_series({}, ["time", "mean"], rows, mode, deadband)["points"]

    def test_a_wobbling_gauge_reports_no_consumption(self):
        # Real readings from a quiet hour on the clean water tank.
        levels = [1298.8, 1298.6, 1299.0, 1298.8, 1299.3, 1299.0, 1298.8, 1299.3]

        assert all(point["v"] == 0.0 for point in self._read(levels))

    def test_noise_is_reported_as_zero_not_dropped(self):
        # A quiet bucket is a measurement that the tank did not move, which is
        # different from having no measurement. It keeps its place on the axis.
        points = self._read([1299.0, 1298.8, 1299.2, 1299.0])

        assert [point["t"] for point in points] == [
            "2026-08-20T00:01:00Z",
            "2026-08-20T00:02:00Z",
        ]

    def test_a_drain_slower_than_the_deadband_is_still_reported_in_full(self):
        # The trap a per-step threshold falls into: no single step here clears
        # 1 L, but the tank really is emptying and the chart has to say so.
        levels = [1300.0, 1299.7, 1299.4, 1299.1, 1298.8, 1298.5, 1298.2, 1297.6, 1297.6]
        points = self._read(levels)

        assert sum(point["v"] for point in points) == pytest.approx(2.4)

    def test_use_still_below_the_deadband_at_the_end_is_carried_not_lost(self):
        # The cost of the deadband, stated exactly: the tail of a slow drain
        # has not yet been confirmed when the window closes, so the total can
        # undercount — but never by more than one deadband.
        levels = [1300.0, 1299.7, 1299.4, 1299.1, 1298.8, 1298.5]
        reported = sum(point["v"] for point in self._read(levels))

        shortfall = (levels[0] - levels[-1]) - reported
        assert reported == pytest.approx(1.2)
        assert 0 <= shortfall < 1.0

    def test_a_drain_is_charged_to_the_bucket_that_confirms_it(self):
        # It accumulates silently against the held reference, then lands whole
        # on the bucket where the level has finally departed far enough.
        assert self._read([1300.0, 1299.7, 1299.4, 1298.9, 1298.9]) == [
            {"t": "2026-08-20T00:01:00Z", "v": 0.0},
            {"t": "2026-08-20T00:02:00Z", "v": 0.0},
            {"t": "2026-08-20T00:03:00Z", "v": 1.1},
        ]

    def test_a_real_draw_survives_untouched(self):
        assert self._read([1376.3, 1317.9, 1317.9]) == [
            {"t": "2026-08-20T00:01:00Z", "v": 58.4}
        ]

    def test_the_deadband_does_not_ratchet_across_a_refill(self):
        # Falling then refilling past the start must not leave phantom use.
        # The draw holds for a second bucket, which is what tells it apart
        # from the one-bucket dip in TestSpikes below.
        levels = [1300.0, 1290.0, 1290.0, 1305.0]

        assert sum(p["v"] for p in self._read(levels)) == 10.0

    def test_delta_keeps_its_sign_through_the_deadband(self):
        points = self._read([100.0, 100.4, 104.0, 103.8, 99.0, 99.0], mode=ts.DELTA)

        assert [point["v"] for point in points] == [0.0, 4.0, 0.0, -5.0]

    def test_zero_deadband_trusts_every_reading(self):
        # The default, and what every non-tank panel still gets.
        points = self._read([100.0, 100.4, 100.1], mode=ts.DELTA, deadband=0.0)

        assert [point["v"] for point in points] == [0.4, -0.3]


class TestSpikes:
    """One bad bucket must not be billed as a movement, still less as two.

    Without this, `drawdown` charged the plunge as use and wrote the recovery
    off as a refill: three real hours of the clean water tank reported 46.2 L
    drawn from a tank that had fallen 38.5 L, one 8.8 L bar of it from a
    single two-minute dip that the very next bucket undid.
    """

    def _read(self, levels, mode=ts.DRAWDOWN, deadband=1.0):
        rows = [[f"2026-08-20T00:{minute:02d}:00Z", v] for minute, v in enumerate(levels)]
        return ts._read_series({}, ["time", "mean"], rows, mode, deadband)["points"]

    def test_a_one_bucket_dip_is_not_charged_as_use(self):
        # The 19:50 bucket, as it was actually recorded. The tank fell 3.75 L
        # across it; the gauge said 8.55 and took it back two minutes later.
        levels = [1966.65, 1958.1, 1962.9, 1962.95]

        assert sum(p["v"] for p in self._read(levels)) == pytest.approx(3.75)

    def test_a_one_bucket_rise_does_not_bank_a_phantom_refill(self):
        # The mirror image, and the subtler half: the spike reads as a refill,
        # which moves the reference UP, and the fall back to where the level
        # always was is then charged as consumption that never happened.
        levels = [1958.75, 1962.5, 1959.0, 1959.0]

        assert sum(p["v"] for p in self._read(levels)) == 0.0

    def test_a_step_is_not_mistaken_for_a_spike(self):
        # A real draw departs and STAYS departed. The second bucket confirms
        # the first, and nothing is smoothed away.
        assert sum(p["v"] for p in self._read([1300.0, 1240.0, 1240.0])) == 60.0

    def test_a_refill_survives_untouched(self):
        assert self._read([1300.0, 1800.0, 1800.0, 1800.0], mode=ts.DELTA) == [
            {"t": "2026-08-20T00:01:00Z", "v": 500.0},
            {"t": "2026-08-20T00:02:00Z", "v": 0.0},
        ]

    def test_a_ramp_is_not_mistaken_for_a_spike(self):
        # Every bucket of a steady drain is beyond the one before it and short
        # of the one after, so none of them is beyond both.
        levels = [1300.0, 1290.0, 1280.0, 1270.0, 1260.0, 1260.0]

        assert sum(p["v"] for p in self._read(levels)) == 40.0

    def test_a_two_bucket_excursion_is_left_alone(self):
        # Two buckets agreeing is evidence; the deadband holds a slow drain to
        # the same standard. Only a lone bucket is overruled.
        levels = [1300.0, 1290.0, 1290.0, 1300.0]

        assert sum(p["v"] for p in self._read(levels)) == 10.0

    def test_wobble_below_the_deadband_is_never_rewritten(self):
        # A bucket is only overruled when it is beyond BOTH neighbours by more
        # than the gauge can resolve. Quiet data reaches the change modes as
        # the level chart drew it, reading for reading.
        levels = [1298.8, 1298.6, 1299.4, 1298.8, 1299.3, 1299.0]
        points = self._read(levels, mode=ts.DELTA, deadband=0.0)

        assert [p["v"] for p in points] == [-0.2, 0.8, -0.6, 0.5, -0.3]

    def test_a_zero_deadband_trusts_every_bucket(self):
        # No declared noise floor, no grounds to call anything a glitch.
        assert self._read([100.0, 90.0, 100.0], mode=ts.DELTA, deadband=0.0) == [
            {"t": "2026-08-20T00:01:00Z", "v": -10.0},
            {"t": "2026-08-20T00:02:00Z", "v": 10.0},
        ]

    def test_too_few_buckets_to_judge_are_left_alone(self):
        # Judging a bucket needs one either side of it, so a pair is returned
        # exactly as it came. Asserted on the rejector itself: two readings
        # never reach the plot anyway, the newer being unconfirmed.
        readings = [("2026-08-20T00:00:00Z", 100.0), ("2026-08-20T00:01:00Z", 90.0)]

        assert ts._reject_spikes(readings, 1.0) == readings


class TestCumulative:
    """How much altogether, rather than how much just then."""

    def _read(self, levels, mode=ts.DRAWDOWN, deadband=1.0):
        rows = [[f"2026-08-20T00:{minute:02d}:00Z", v] for minute, v in enumerate(levels)]
        return ts._read_series({}, ["time", "mean"], rows, mode, deadband, True)["points"]

    def test_the_total_only_climbs(self):
        assert [p["v"] for p in self._read([1300.0, 1290.0, 1290.0, 1275.0, 1275.0])] == [
            10.0,
            10.0,
            25.0,
        ]

    def test_a_quiet_bucket_holds_the_total_level(self):
        # Not a gap and not a fall — nothing was drawn, so the total stands.
        assert [p["v"] for p in self._read([1300.0, 1299.9, 1299.8, 1299.8])] == [0.0, 0.0]

    def test_a_refill_does_not_pull_the_total_back_down(self):
        # This is water drawn, not water missing. Putting 500 L in does not
        # unuse what the crew already used.
        assert [p["v"] for p in self._read([1300.0, 1280.0, 1280.0, 1780.0, 1780.0])] == [
            20.0,
            20.0,
            20.0,
        ]

    def test_the_last_point_is_the_sum_of_the_bars(self):
        # The running total and the per-bucket chart beside it are the same
        # numbers; a reader adding up the bars must land on the line's end.
        levels = [1300.0, 1290.0, 1290.0, 1291.0, 1275.0, 1275.0]
        rows = [[f"2026-08-20T00:{m:02d}:00Z", v] for m, v in enumerate(levels)]

        bars = ts._read_series({}, ["time", "mean"], rows, ts.DRAWDOWN, 1.0)["points"]
        total = self._read(levels)[-1]["v"]

        assert total == pytest.approx(sum(p["v"] for p in bars))

    def test_cumulative_mean_is_refused(self):
        # A running total of temperature is a number with no referent.
        with pytest.raises(QueryError):
            ts.series("Temperature", "value", "1h", cumulative=True)


class TestModeValidation:
    def test_unknown_mode_is_refused(self):
        with pytest.raises(QueryError):
            ts.series("Temperature", "value", "1h", mode="wishful")

    def test_a_negative_deadband_is_refused(self):
        with pytest.raises(QueryError):
            ts.series("Water", "litres", "1h", mode=ts.DRAWDOWN, deadband=-1.0)


class TestSeed:
    """What the first reported change is measured against.

    A held reference makes every bar relative to where that reference started,
    so a seed taken from one raw sample puts the gauge's dither into the whole
    window. On the clean water tank at 22:50 on 2026-08-21 that made the same
    bar read anywhere from 2.3 L to 3.2 L depending only on which minute the
    chart opened — two ranges of one dashboard disagreeing about one minute.

    A wider seed narrows that and cannot close it. The gauge knows a still
    level to about its own noise floor and no better, so what a 3.5 L draw fell
    FROM is only ever known to within that floor, and no amount of arithmetic
    recovers a measurement nobody made. The bar is a real quantity with a real
    uncertainty; the goal here is to keep the disagreement inside the floor
    rather than outside it, not to pretend it away.
    """

    def _bar(self, levels, start, seeds, deadband=1.0):
        """The first reported bar, for a window opening at `start`."""
        rows = [
            [f"2026-08-20T00:{minute:02d}:00Z", v]
            for minute, v in enumerate(levels)
        ][start:]
        points = ts._read_series({}, ["time", "mean"], rows, ts.DRAWDOWN, deadband,
                                 False, seeds)["points"]
        return next((p["v"] for p in points if p["v"]), 0.0)

    # The gauge itself, 2026-08-21 22:34-22:53 UTC: the tank sitting still,
    # then the draw the two ranges disagreed about.
    QUIET = [1933.8, 1933.4, 1933.7, 1933.6, 1933.6, 1933.9, 1933.8, 1933.8,
             1933.8, 1933.7, 1933.4, 1934.1, 1933.4, 1933.6, 1933.4, 1933.8]
    DRAW = [1931.1, 1930.3, 1930.1, 1930.8, 1930.4]

    def test_one_sample_seed_makes_the_bar_depend_on_the_window(self):
        # The defect, held in place so it cannot come back unnoticed. Ten
        # windows over one draw, and five different answers about it.
        bars = {self._bar(self.QUIET + self.DRAW, start, seeds=1) for start in range(10)}

        assert max(bars) - min(bars) == pytest.approx(0.5)

    def test_a_wider_seed_narrows_the_disagreement(self):
        # Narrowed, not abolished — see the class docstring. What matters is
        # that it now sits inside the gauge's own noise floor: the charts no
        # longer disagree by more than the instrument can resolve, which is as
        # close to agreement as this gauge can support.
        bars = {self._bar(self.QUIET + self.DRAW, start, seeds=5) for start in range(10)}

        assert max(bars) - min(bars) < 1.0  # the tank's deadband

    def test_the_seed_lands_on_the_settled_level(self):
        # Not merely consistent — right. The tank sat at about 1933.7.
        assert ts._seed_reference(self.QUIET[:5], 1.0) == pytest.approx(1933.7, abs=0.2)

    def test_a_window_opening_mid_draw_anchors_on_the_latest_reading(self):
        # A median would sit behind a moving level and charge the lag as use.
        falling = [1300.0, 1290.0, 1280.0, 1270.0, 1260.0]

        assert ts._seed_reference(falling, 1.0) == 1260.0

    def test_a_still_lead_in_anchors_on_the_median(self):
        assert ts._seed_reference([1000.4, 999.7, 1000.3, 999.6, 1000.2], 1.0) == 1000.2

    def test_stillness_is_judged_by_trend_not_by_spread(self):
        # Peak-to-peak grows with how many readings you look at, so a spread
        # test calls a still tank moving once the lead-in is wide enough. Every
        # step here exceeds the deadband; the level goes nowhere.
        wobble = [1000.0, 1001.2, 999.0, 1001.1, 999.1, 1001.0, 999.2]

        assert ts._seed_reference(wobble, 1.0) == pytest.approx(1000.0)

    def test_an_untrusted_instrument_still_seeds_on_one_reading(self):
        # No declared noise floor, no grounds to call any spread dither.
        assert ts._seed_reference([100.0, 200.0, 300.0], 0.0) == 300.0

    def test_the_seed_never_eats_the_window(self):
        # A gappy lead-in returns fewer readings than buckets were asked for,
        # and the shortfall must not come out of the plot.
        rows = [["2026-08-20T00:00:00Z", 100.0], ["2026-08-20T00:01:00Z", 80.0],
                ["2026-08-20T00:02:00Z", 80.0]]
        points = ts._read_series({}, ["time", "mean"], rows, ts.DRAWDOWN,
                                 1.0, False, 20)["points"]

        assert [p["v"] for p in points] == [20.0]


class TestUnconfirmedEdge:
    """The newest bucket has no successor, so no one can vouch for it.

    `_reject_spikes` judges a bucket against both neighbours, which the last
    one does not have. Charged anyway, a glitch at the live edge is billed in
    full on every refresh: the 19:51 bucket on 2026-08-21 read 1949.2 L between
    neighbours of 1967.0 and 1962.8 and was charged as 17.4 L of use, against
    the 4.2 L that had really gone.
    """

    def _read(self, levels, deadband=1.0):
        rows = [[f"2026-08-20T00:{m:02d}:00Z", v] for m, v in enumerate(levels)]
        return ts._read_series({}, ["time", "mean"], rows, ts.DRAWDOWN, deadband)["points"]

    def test_a_glitch_in_the_newest_bucket_is_not_charged(self):
        assert sum(p["v"] for p in self._read([1967.0, 1966.8, 1949.2])) == 0.0

    def test_the_newest_bucket_is_held_back_not_zeroed(self):
        # Reporting it as zero would be a claim that nothing moved, which is
        # exactly what is not yet known. It has no point at all.
        points = self._read([1000.0, 1000.0, 990.0])

        assert [p["t"] for p in points] == ["2026-08-20T00:01:00Z"]

    def test_a_real_draw_is_charged_whole_once_confirmed(self):
        # Nothing is lost to the delay: the reference does not move while the
        # bucket waits, so the next one charges the full amount.
        points = self._read([1000.0, 1000.0, 990.0, 990.0])

        assert [(p["t"], p["v"]) for p in points if p["v"]] == [
            ("2026-08-20T00:02:00Z", 10.0)
        ]

    def test_an_untrusted_instrument_reports_its_newest_bucket(self):
        # With no noise floor there is no spike rejection to wait for, and
        # holding a bucket back would only lose a reading the caller trusts.
        points = ts._read_series(
            {}, ["time", "mean"],
            [["2026-08-20T00:00:00Z", 100.0], ["2026-08-20T00:01:00Z", 90.0]],
            ts.DELTA, 0.0,
        )["points"]

        assert [p["v"] for p in points] == [-10.0]


class TestSeedBuckets:
    def test_short_buckets_seed_from_several(self):
        # A 1-minute bucket holds one sample and carries the dither whole.
        assert ts.seed_buckets(1) == 5
        assert ts.seed_buckets(2) == 3

    def test_long_buckets_seed_from_one(self):
        # These already average SEED_MINUTES or more inside the bucket.
        for bucket in (5, 10, 30, 60, 180, 360):
            assert ts.seed_buckets(bucket) == 1

    def test_every_range_seeds_at_least_one_bucket(self):
        for _, bucket in ts.RANGES.values():
            assert ts.seed_buckets(bucket) >= 1
