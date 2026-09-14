"""The query-building layer is where a language model's output becomes SQL-ish.

These tests pin the parts that must never loosen: identifier validation, the
read-only guard, and the difference between a rolling window and an absolute
one.
"""

import pytest

from app.core.errors import DatasourceError, QueryError
from app.datasource.wire import assert_read_only
from app.telemetry import influxql as ql


class TestIdentifier:
    def test_accepts_ordinary_names(self):
        assert ql.identifier("Temperature") == '"Temperature"'
        assert ql.identifier("total_forward_energy") == '"total_forward_energy"'
        assert ql.identifier("PM2.5") == '"PM2.5"'

    @pytest.mark.parametrize(
        "hostile",
        [
            'Temperature"; DROP MEASUREMENT x',
            "Temp'--",
            "a) OR (1=1",
            "",
            "back`tick",
        ],
    )
    def test_refuses_anything_surprising(self, hostile):
        # Refusing beats escaping: the model chooses these strings.
        with pytest.raises(QueryError):
            ql.identifier(hostile)

    def test_refuses_non_strings(self):
        with pytest.raises(QueryError):
            ql.identifier(None)


class TestLiteral:
    def test_wraps_in_single_quotes(self):
        assert ql.literal("Atrium") == "'Atrium'"

    def test_escapes_quotes_and_backslashes(self):
        assert ql.literal("O'Brien") == "'O\\'Brien'"
        assert ql.literal("back\\slash") == "'back\\\\slash'"


class TestReadOnlyGuard:
    @pytest.mark.parametrize(
        "query",
        ["SELECT value FROM Temperature", "SHOW MEASUREMENTS", "  select 1"],
    )
    def test_allows_reads(self, query):
        assert_read_only(query)  # does not raise

    @pytest.mark.parametrize(
        "query",
        [
            "DROP MEASUREMENT Temperature",
            "DELETE FROM Temperature",
            "SELECT * INTO copy FROM Temperature",
            "SELECT 1; DROP DATABASE HABITAT",
        ],
    )
    def test_refuses_writes_and_chaining(self, query):
        with pytest.raises(DatasourceError):
            assert_read_only(query)


class TestTimestamp:
    def test_normalises_to_utc(self):
        assert ql.timestamp("2026-08-18T05:00:00Z") == "'2026-08-18T05:00:00Z'"

    def test_converts_offsets_to_utc(self):
        # 07:00 CEST is 05:00 UTC — getting this wrong silently shifts the
        # whole answer by two hours.
        assert ql.timestamp("2026-08-18T07:00:00+02:00") == "'2026-08-18T05:00:00Z'"

    def test_assumes_utc_when_no_zone_given(self):
        assert ql.timestamp("2026-08-18T05:00:00") == "'2026-08-18T05:00:00Z'"

    def test_refuses_nonsense(self):
        with pytest.raises(QueryError):
            ql.timestamp("last Tuesday")


class TestWindow:
    def test_no_arguments_means_all_history(self):
        clauses, label = ql.window()
        assert clauses == []
        assert label == "all available data"

    def test_days_builds_a_rolling_window(self):
        clauses, label = ql.window(days=3)
        assert clauses == ["time > now() - 4320m"]
        assert "rolling" in label

    def test_start_and_end_are_absolute(self):
        clauses, label = ql.window(start="2026-08-18T05:00:00Z", end="2026-08-19T05:00:00Z")
        assert clauses == [
            "time >= '2026-08-18T05:00:00Z'",
            "time <= '2026-08-19T05:00:00Z'",
        ]
        assert "from" in label and "to" in label

    def test_start_without_end_runs_to_now(self):
        clauses, label = ql.window(start="2026-08-18T05:00:00Z")
        assert clauses == ["time >= '2026-08-18T05:00:00Z'"]
        assert label.endswith("to now")

    def test_absolute_beats_relative(self):
        # A question naming a specific moment must not be turned into an
        # approximate number of days measured backwards from now.
        clauses, _ = ql.window(days=7, start="2026-08-18T05:00:00Z")
        assert clauses == ["time >= '2026-08-18T05:00:00Z'"]


class TestLeadIn:
    """Differencing a level needs one bucket of history before the window."""

    def test_a_rolling_window_reaches_further_back_to_get_it(self):
        clauses, label = ql.window(days=3, lead_minutes=15)
        assert clauses == ["time > now() - 4335m"]
        # The label still names the window that was asked about.
        assert "3 day" in label

    def test_an_absolute_start_is_shifted_back_but_still_labelled_as_asked(self):
        clauses, label = ql.window(start="2026-08-18T05:00:00Z", lead_minutes=60)
        assert clauses == ["time >= '2026-08-18T04:00:00Z'"]
        assert "2026-08-18T05:00:00Z" in label

    def test_no_lead_leaves_the_window_exactly_as_asked(self):
        assert ql.window(days=3)[0] == ["time > now() - 4320m"]


class TestWindowSpan:
    """What a per-day average must divide by."""

    def test_a_rolling_window_spans_the_days_it_names(self):
        assert ql.window_span_days(days=3) == 3.0

    def test_an_absolute_range_spans_its_own_length(self):
        span = ql.window_span_days(
            start="2026-08-18T00:00:00Z", end="2026-08-21T00:00:00Z"
        )
        assert span == 3.0

    def test_the_span_ignores_which_calendar_days_it_touches(self):
        # This window touches four UTC days and is three days long. Dividing a
        # total by four would understate every daily figure by a quarter.
        span = ql.window_span_days(
            start="2026-08-18T09:00:00Z", end="2026-08-21T09:00:00Z"
        )
        assert span == 3.0

    def test_all_history_has_no_knowable_span(self):
        assert ql.window_span_days() is None

    def test_an_end_without_a_start_has_no_knowable_span(self):
        assert ql.window_span_days(end="2026-08-21T00:00:00Z") is None


class TestBuckets:
    def test_known_sizes(self):
        assert ql.bucket_minutes("hour") == 60
        assert ql.bucket_minutes("day") == 1440
        assert ql.bucket_minutes("week") == 10080

    def test_refuses_unknown(self):
        with pytest.raises(QueryError):
            ql.bucket_minutes("fortnight")


class TestTrimPeriods:
    def test_short_lists_pass_through(self):
        periods = [{"n": i} for i in range(5)]
        kept, truncated = ql.trim_periods(periods)
        assert kept == periods
        assert truncated is False

    def test_keeps_the_most_recent(self):
        periods = [{"n": i} for i in range(ql.MAX_PERIODS + 10)]
        kept, truncated = ql.trim_periods(periods)
        assert truncated is True
        assert len(kept) == ql.MAX_PERIODS
        assert kept[-1]["n"] == ql.MAX_PERIODS + 9


class TestWhereClause:
    def test_empty_becomes_a_tautology(self):
        assert ql.where_clause([]) == "1 = 1"

    def test_joins_with_and(self):
        assert ql.where_clause(["a = 1", "b = 2"]) == "a = 1 AND b = 2"
