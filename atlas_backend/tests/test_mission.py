"""The mission plan: its calendar, its arithmetic, and its verdicts.

No network. Every test here either does arithmetic or talks to a throwaway
database, so the suite still runs with no habitat in sight.

The load-bearing property, asserted from several directions, is that the day
plan sums to the ceiling. Everything the page says is a sum over that plan, so
if the identity holds the three windows cannot disagree with each other, and if
it breaks they will disagree quietly.
"""

from datetime import UTC, date, datetime, timedelta

import pytest

from app.core.errors import AtlasError
from app.mission import dayplan as dp
from app.mission import meters as mt
from app.mission import periods as per
from app.mission import plan as pl
from app.mission import repository as repo
from app.mission import tracking as track
from app.mission.brief import mission_brief
from app.schemas.mission import Budget, PlannedDay, ResourceTracking, Tracking
from app.telemetry import influxql as ql
from app.telemetry import tanks

# UTC+02:00, the habitat's clock in the shipped figures.
OFFSET = 120

START = date(2026, 8, 10)
MISSION = pl.Mission(name="Reference VII", start=START, days=30)


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


def _extra(**kwargs) -> pl.Extra:
    fields = {
        "id": kwargs.get("id", "x"),
        "resource": "water",
        "label": "an extra",
        "amount": 100.0,
        "kind": pl.ONCE,
        "on_date": None,
        "note": "",
    }
    fields.update(kwargs)
    return pl.Extra(**fields)  # type: ignore[arg-type]


class TestLocalCalendar:
    """A day that is not a UTC day."""

    def test_local_midnight_is_the_utc_instant_the_local_day_began(self):
        # 00:00 on the 22nd in UTC+02:00 happened at 22:00 UTC on the 21st.
        assert per.start_of_local_day(date(2026, 8, 22), OFFSET) == _utc(
            "2026-08-21T22:00:00Z"
        )

    def test_the_two_hours_before_utc_midnight_are_already_tomorrow(self):
        # The whole point of the offset. At 22:30 UTC the habitat has been in
        # the 22nd for half an hour, and a UTC day would file it under the 21st.
        assert per.local_date(_utc("2026-08-21T22:30:00Z"), OFFSET) == date(2026, 8, 22)
        assert per.local_date(_utc("2026-08-21T21:30:00Z"), OFFSET) == date(2026, 8, 21)

    def test_a_zero_offset_is_the_utc_day(self):
        assert per.start_of_local_day(date(2026, 8, 22), 0) == _utc("2026-08-22T00:00:00Z")

    def test_local_days_walks_dates_inclusively(self):
        days = per.local_days(date(2026, 8, 20), date(2026, 8, 22), OFFSET)

        assert [per.iso(day) for day in days] == [
            "2026-08-19T22:00:00Z",
            "2026-08-20T22:00:00Z",
            "2026-08-21T22:00:00Z",
        ]

    def test_the_offset_label_reads_as_a_clock_setting(self):
        assert per.offset_label(120) == "UTC+02:00"
        assert per.offset_label(0) == "UTC+00:00"
        assert per.offset_label(-330) == "UTC-05:30"

    def test_the_share_of_today_that_has_passed_is_read_in_local_time(self):
        # 12:00 UTC is 14:00 in the habitat: seven twelfths of its day.
        share = per.day_elapsed_fraction(_utc("2026-08-22T12:00:00Z"), OFFSET)

        assert share == pytest.approx(14 / 24, abs=1e-6)


class TestMissionShape:
    """The three declared facts, and what follows from them."""

    def test_a_mission_needs_both_a_start_and_a_length(self):
        assert not pl.Mission(start=START).is_declared
        assert not pl.Mission(days=30).is_declared
        assert MISSION.is_declared

    def test_the_end_is_derived_so_the_two_can_never_disagree(self):
        # 30 days from the 10th ends on the 8th, both ends counted.
        assert MISSION.end == date(2026, 9, 8)
        assert (MISSION.end - MISSION.start).days + 1 == MISSION.days

    def test_mission_days_are_one_based_because_nobody_says_md_zero(self):
        assert MISSION.day_index(START) == 1
        assert MISSION.day_index(date(2026, 8, 23)) == 14
        assert MISSION.date_of(14) == date(2026, 8, 23)

    def test_a_day_outside_the_mission_is_outside_it(self):
        assert not MISSION.contains(date(2026, 8, 9))
        assert not MISSION.contains(date(2026, 9, 9))
        assert MISSION.contains(date(2026, 9, 8))

    def test_the_code_is_zero_padded_so_a_column_of_them_lines_up(self):
        assert pl.day_code(1) == "MD-01"
        assert pl.day_code(30) == "MD-30"


class TestCycles:
    """Three-day blocks, counted from MD-01 and not from a calendar week."""

    def test_the_first_cycle_is_md01_to_md03(self):
        assert dp.cycle_bounds(MISSION, START) == (1, 3)
        assert dp.cycle_number(MISSION, START) == 1

    def test_a_day_inside_a_cycle_reports_that_cycle_not_itself(self):
        # MD-14 sits in the fifth block, MD-13 to MD-15.
        assert dp.cycle_bounds(MISSION, date(2026, 8, 23)) == (13, 15)
        assert dp.cycle_number(MISSION, date(2026, 8, 23)) == 5

    def test_the_last_cycle_is_short_rather_than_running_past_the_end(self):
        # A 30-day mission divides evenly; a 29-day one does not, and the last
        # block has to stop at the last day rather than budget a day that is
        # not in the mission.
        short = pl.Mission(start=START, days=29)
        assert dp.cycle_bounds(short, short.date_of(29)) == (28, 29)

    def test_there_is_no_cycle_outside_the_mission(self):
        assert dp.cycle_bounds(MISSION, date(2026, 8, 1)) is None
        assert dp.cycle_bounds(pl.Mission(), date(2026, 8, 1)) is None


class TestTheDayPlan:
    """A ceiling and a duration in, an allowance per day out."""

    def _build(self, total=3000.0, extras=(), today=START, used=None):
        return dp.build(
            "water", total, MISSION, list(extras), used or {}, today
        )

    def test_the_plan_sums_to_the_ceiling_exactly(self):
        built = self._build()

        assert sum(day.planned for day in built.days) == pytest.approx(3000.0)
        assert len(built.days) == 30

    def test_it_still_sums_to_the_ceiling_once_extras_are_booked(self):
        # The identity that matters: an extra moves where the ceiling is spent,
        # never how much of it there is.
        built = self._build(
            extras=[
                _extra(id="a", amount=300.0, on_date=date(2026, 8, 23)),
                _extra(id="b", amount=12.0, kind=pl.DAILY),
            ]
        )

        assert sum(day.planned for day in built.days) == pytest.approx(3000.0)

    def test_an_extra_lowers_every_other_day_rather_than_raising_the_total(self):
        flat = self._build().flat_per_day
        with_extra = self._build(extras=[_extra(amount=300.0, on_date=date(2026, 8, 23))])

        assert with_extra.flat_per_day < flat
        assert with_extra.flat_per_day == pytest.approx((3000.0 - 300.0) / 30)

    def test_a_daily_extra_lands_on_every_single_day(self):
        built = self._build(extras=[_extra(kind=pl.DAILY, amount=12.0)])

        assert all(day.extras == 12.0 for day in built.days)
        assert built.extras_total == pytest.approx(12.0 * 30)

    def test_a_one_off_lands_on_its_day_and_nowhere_else(self):
        built = self._build(extras=[_extra(amount=300.0, on_date=date(2026, 8, 23))])
        loaded = [day for day in built.days if day.extras]

        assert [day.code for day in loaded] == ["MD-14"]
        assert loaded[0].planned == pytest.approx(built.flat_per_day + 300.0)

    def test_extras_beyond_the_ceiling_floor_the_flat_rate_and_say_so(self):
        built = self._build(total=100.0, extras=[_extra(amount=500.0, on_date=START)])

        assert built.flat_per_day == 0.0
        assert any("more than the whole ceiling" in note for note in built.notes)

    def test_no_ceiling_means_no_allowance_rather_than_a_guess(self):
        built = self._build(total=None)

        assert built.total is None
        assert all(day.revised is None for day in built.days)


class TestTheForwardPlan:
    """What a day may cost from here, given what has already gone."""

    def _built(self, used, today, total=3000.0, extras=()):
        return dp.build("water", total, MISSION, list(extras), used, today)

    def test_overspending_early_lowers_every_day_that_is_left(self):
        # MD-01 to MD-09 at 150 against a plan of 100 — 450 over.
        used = {START + timedelta(days=n): 150.0 for n in range(9)}
        built = self._built(used, today=START + timedelta(days=9))

        assert built.consumed == pytest.approx(1350.0)
        assert built.remaining == pytest.approx(1650.0)
        # 21 days left, today included.
        assert built.days_remaining == 21
        assert built.revised_per_day == pytest.approx(1650.0 / 21, abs=1e-3)
        assert built.revised_per_day < built.flat_per_day

    def test_underspending_hands_the_slack_back_to_the_days_ahead(self):
        used = {START + timedelta(days=n): 50.0 for n in range(9)}
        built = self._built(used, today=START + timedelta(days=9))

        assert built.revised_per_day > built.flat_per_day

    def test_today_counts_as_a_day_still_to_come(self):
        # Otherwise the whole of today's overspend is handed to tomorrow, and
        # the crew is told to make up the difference on a day that has not
        # started.
        built = self._built({}, today=START)

        assert built.days_remaining == 30
        assert built.days[0].revised is not None

    def test_a_day_already_behind_us_is_not_re_planned(self):
        built = self._built({}, today=START + timedelta(days=5))
        past = [day for day in built.days if day.state == dp.PAST]

        assert past and all(day.revised is None for day in past)

    def test_extras_still_to_come_are_reserved_before_the_rest_is_spread(self):
        extras = [_extra(amount=300.0, on_date=date(2026, 8, 23))]
        built = self._built({}, today=START, extras=extras)

        # 3000 less the 300 still booked, over 30 days.
        assert built.extras_to_come == pytest.approx(300.0)
        assert built.revised_per_day == pytest.approx(2700.0 / 30)

    def test_a_plan_that_no_longer_closes_says_so_instead_of_going_negative(self):
        used = {START + timedelta(days=n): 400.0 for n in range(7)}
        extras = [_extra(amount=400.0, on_date=date(2026, 8, 23))]
        built = self._built(used, today=START + timedelta(days=7), extras=extras)

        assert built.remaining == pytest.approx(200.0)
        assert not built.feasible
        assert built.shortfall == pytest.approx(200.0)
        # Floored, never published as a negative allowance nobody can act on.
        assert built.revised_per_day == 0.0
        assert any("short by" in note for note in built.notes)

    def test_a_day_the_sensors_missed_is_not_counted_as_a_day_of_none(self):
        used = {START: 150.0, START + timedelta(days=2): 150.0}
        built = self._built(used, today=START + timedelta(days=3))

        # MD-02 had no readings, and neither has today. Both are unknown, and
        # neither is a day of zero.
        assert built.days_measured == 2
        assert built.days_uncovered == 2
        assert built.consumed == pytest.approx(300.0)
        assert any("no readings" in note for note in built.notes)


class TestDayVerdicts:
    """How a single mission day is judged against its allowance."""

    def test_a_day_well_past_its_allowance_is_over(self):
        assert dp._verdict(150.0, 100.0, partial=False) == dp.OVER

    def test_a_day_within_the_tolerance_went_to_plan(self):
        assert dp._verdict(101.0, 100.0, partial=False) == dp.ON_PLAN
        assert dp._verdict(99.0, 100.0, partial=False) == dp.ON_PLAN

    def test_a_day_still_running_cannot_be_under_its_allowance(self):
        # The single most reassuring wrong thing this page could say: "under
        # plan" at 08:00 on a day with the whole afternoon still to go.
        assert dp._verdict(10.0, 100.0, partial=True) == dp.ON_PLAN
        assert dp._verdict(10.0, 100.0, partial=False) == dp.UNDER

    def test_a_day_still_running_can_already_be_over(self):
        assert dp._verdict(150.0, 100.0, partial=True) == dp.OVER

    def test_a_day_allowed_nothing_is_broken_by_any_draw_at_all(self):
        assert dp._verdict(0.1, 0.0, partial=False) == dp.OVER
        assert dp._verdict(0.0, 0.0, partial=False) == dp.ON_PLAN


class TestValidation:
    """What the plan refuses, and what it says when it does."""

    def test_a_negative_ceiling_is_refused(self):
        with pytest.raises(AtlasError, match="must not be negative"):
            pl.validate_total("water", -1)

    def test_zero_is_allowed_because_it_is_a_real_plan(self):
        assert pl.validate_total("water", 0) == 0.0

    def test_clearing_a_ceiling_is_allowed(self):
        assert pl.validate_total("water", None) is None

    def test_an_unknown_resource_is_refused(self):
        with pytest.raises(AtlasError, match="Unknown resource"):
            pl.validate_total("oxygen", 1)

    def test_a_figure_beyond_any_habitat_is_refused_as_a_units_mistake(self):
        with pytest.raises(AtlasError, match="Check the units"):
            pl.validate_total("water", pl.MAX_TOTAL + 1)

    def test_a_mission_cannot_end_before_it_starts(self):
        with pytest.raises(AtlasError, match="at least"):
            pl.validate_mission("", "2026-08-10", 0)

    def test_a_mission_longer_than_the_page_lays_out_is_refused(self):
        with pytest.raises(AtlasError, match="cap is"):
            pl.validate_mission("", "2026-08-10", pl.MAX_MISSION_DAYS + 1)

    def test_the_day_boundary_must_be_a_whole_hour(self):
        with pytest.raises(AtlasError, match="whole number of hours"):
            pl.normalise_offset(90)

    def test_the_day_boundary_must_be_a_real_offset(self):
        with pytest.raises(AtlasError, match="between"):
            pl.normalise_offset(20 * 60)

    def test_an_extra_needs_a_label_somebody_can_audit(self):
        with pytest.raises(AtlasError, match="Give the extra a label"):
            pl.validate_extra(
                {"resource": "water", "label": "  ", "amount": 5}, MISSION
            )

    def test_an_extra_needs_an_amount(self):
        with pytest.raises(AtlasError, match="How much"):
            pl.validate_extra(
                {"resource": "water", "label": "Algae", "amount": None}, MISSION
            )

    def test_a_one_off_needs_a_day_to_come_out_of(self):
        with pytest.raises(AtlasError, match="needs the day it happens on"):
            pl.validate_extra(
                {"resource": "water", "label": "Algae", "amount": 5}, MISSION
            )

    def test_a_daily_extra_needs_no_day_at_all(self):
        checked = pl.validate_extra(
            {"resource": "water", "label": "Dishes", "amount": 12, "kind": "daily"},
            MISSION,
        )

        assert checked["on_date"] is None

    def test_a_mission_day_number_is_resolved_to_its_date(self):
        checked = pl.validate_extra(
            {
                "resource": "water",
                "label": "Algae",
                "amount": 300,
                "mission_day": 14,
            },
            MISSION,
        )

        assert checked["on_date"] == date(2026, 8, 23)

    def test_a_mission_day_beyond_the_mission_is_refused(self):
        with pytest.raises(AtlasError, match="MD-01 to MD-30"):
            pl.validate_extra(
                {"resource": "water", "label": "Algae", "amount": 1, "mission_day": 44},
                MISSION,
            )

    def test_a_date_outside_the_mission_is_refused_as_budgeting_nothing(self):
        with pytest.raises(AtlasError, match="outside this mission"):
            pl.validate_extra(
                {
                    "resource": "water",
                    "label": "Algae",
                    "amount": 1,
                    "on_date": "2027-01-01",
                },
                MISSION,
            )


class TestRepository:
    """What survives a restart, and what a row means."""

    def test_an_untouched_plan_has_no_mission_and_no_ceilings(self, temp_database):
        stored = repo.load_plan()

        assert not stored.is_declared
        assert stored.is_all_default
        assert all(stored.total(resource) is None for resource in pl.RESOURCES)

    def test_the_mission_survives_a_round_trip(self, temp_database):
        repo.save_mission(MISSION)
        stored = repo.load_plan().mission

        assert stored.name == "Reference VII"
        assert stored.start == START
        assert stored.days == 30
        assert stored.end == date(2026, 9, 8)

    def test_a_saved_ceiling_is_marked_as_the_crews(self, temp_database):
        repo.save_totals({"water": 4500.0})
        stored = repo.load_plan()

        assert stored.total("water") == 4500.0
        assert stored.source("water") == pl.CREW
        assert stored.source("power") == pl.DEFAULT
        assert not stored.is_all_default

    def test_saving_one_resource_leaves_the_other_alone(self, temp_database):
        repo.save_totals({"water": 4500.0})
        repo.save_totals({"power": 1500.0})
        stored = repo.load_plan()

        assert stored.total("water") == 4500.0
        assert stored.total("power") == 1500.0

    def test_a_cleared_ceiling_is_a_decision_not_an_absence(self, temp_database):
        repo.save_totals({"water": 4500.0})
        repo.save_totals({"water": None})
        stored = repo.load_plan()

        assert stored.total("water") is None
        # Still the crew's: they looked and chose not to cap it.
        assert stored.source("water") == pl.CREW

    def test_extras_survive_and_come_back_ordered(self, temp_database):
        repo.save_mission(MISSION)
        plan = repo.load_plan()
        for label, day in (("Zulu", 20), ("Alpha", 3)):
            repo.add_extra(
                pl.validate_extra(
                    {
                        "resource": "water",
                        "label": label,
                        "amount": 10,
                        "mission_day": day,
                    },
                    plan.mission,
                )
            )
        repo.add_extra(
            pl.validate_extra(
                {
                    "resource": "water",
                    "label": "Dishes",
                    "amount": 12,
                    "kind": "daily",
                },
                plan.mission,
            )
        )

        labels = [extra.label for extra in repo.load_plan().extras_for("water")]

        # Daily first — it applies to every day — then by the day they land on.
        assert labels == ["Dishes", "Alpha", "Zulu"]

    def test_an_extra_can_be_edited_and_removed(self, temp_database):
        repo.save_mission(MISSION)
        plan = repo.load_plan()
        fields = pl.validate_extra(
            {"resource": "water", "label": "Algae", "amount": 300, "mission_day": 14},
            plan.mission,
        )
        identifier = repo.add_extra(fields)

        repo.update_extra(identifier, {**fields, "amount": 250.0})
        assert repo.load_plan().extras[0].amount == 250.0

        repo.delete_extra(identifier)
        assert repo.load_plan().extras == ()

    def test_editing_an_extra_somebody_else_removed_is_refused_clearly(
        self, temp_database
    ):
        repo.save_mission(MISSION)
        fields = pl.validate_extra(
            {"resource": "water", "label": "Algae", "amount": 300, "mission_day": 1},
            MISSION,
        )

        with pytest.raises(AtlasError, match="no longer in the plan"):
            repo.update_extra("nothing-with-this-id", fields)

    def test_deleting_an_extra_twice_is_not_an_error(self, temp_database):
        repo.delete_extra("nothing-with-this-id")

    def test_moving_the_mission_strands_an_extra_rather_than_deleting_it(
        self, temp_database
    ):
        repo.save_mission(MISSION)
        repo.add_extra(
            pl.validate_extra(
                {
                    "resource": "water",
                    "label": "Algae",
                    "amount": 300,
                    "mission_day": 28,
                },
                MISSION,
            )
        )
        # The mission shortens under it. The crew put the extra there, so it
        # stays — but it now comes out of no day's allowance, and the plan says
        # so rather than silently dropping 300 litres of intent.
        repo.save_mission(pl.Mission(name="Reference VII", start=START, days=5))
        stored = repo.load_plan()

        assert len(stored.extras) == 1
        assert any("outside the mission's dates" in w for w in stored.warnings)

    def test_a_reset_clears_the_mission_the_ceilings_and_the_extras(
        self, temp_database
    ):
        repo.save_mission(MISSION)
        repo.save_totals({"water": 4500.0})
        repo.add_extra(
            pl.validate_extra(
                {"resource": "water", "label": "Dishes", "amount": 12, "kind": "daily"},
                MISSION,
            )
        )

        repo.reset_plan()
        stored = repo.load_plan()

        assert not stored.is_declared
        assert stored.is_all_default
        assert stored.extras == ()

    def test_a_ceiling_for_a_resource_this_build_dropped_is_kept_but_ignored(
        self, temp_database
    ):
        repo.save_totals({"unobtainium": 5.0})
        stored = repo.load_plan()

        assert "unobtainium" not in stored.totals
        assert stored.is_all_default

    def test_an_unreadable_mission_length_lands_on_the_setup_not_on_a_500(
        self, temp_database
    ):
        repo.save_setting(repo.START_KEY, START.isoformat())
        repo.save_setting(repo.DAYS_KEY, "not a number")

        assert not repo.load_plan().is_declared


class TestShippedDefaults:
    def test_the_shipped_figures_cover_every_resource(self):
        defaults = pl.load_defaults()

        assert set(defaults["suggested_daily"]) == set(pl.RESOURCES)

    def test_the_shipped_day_boundary_is_a_whole_hour(self):
        assert pl.load_defaults()["day_start_offset_minutes"] % 60 == 0

    def test_a_suggested_ceiling_is_the_daily_figure_across_the_mission(self):
        stored = pl.Plan(
            totals={},
            sources={},
            day_start_offset_minutes=0,
            mission=MISSION,
            suggested_daily={"water": 150.0},
        )

        assert stored.suggested_total("water") == 4500.0

    def test_nothing_is_suggested_before_a_mission_is_declared(self):
        stored = pl.Plan(
            totals={},
            sources={},
            day_start_offset_minutes=0,
            suggested_daily={"water": 150.0},
        )

        assert stored.suggested_total("water") is None


class TestWindowVerdicts:
    """One window of the day plan against what the meters said."""

    def _budget(self, now: str, used: dict, total=3000.0, extras=(), horizon="day"):
        stored = pl.Plan(
            totals={"water": total},
            sources={"water": pl.CREW},
            day_start_offset_minutes=OFFSET,
            mission=MISSION,
            extras=tuple(extras),
        )
        moment = _utc(now)
        today = per.local_date(moment, OFFSET)
        built = dp.build("water", total, MISSION, list(extras), used, today)
        live = per.current_periods(moment, OFFSET, MISSION)
        return track._budget(
            live[horizon],
            built,
            stored,
            "water",
            per.day_elapsed_fraction(moment, OFFSET),
        )

    def test_a_day_budget_is_that_days_allowance_and_nothing_else(self):
        budget = self._budget("2026-08-23T10:00:00Z", {date(2026, 8, 23): 40.0})

        assert budget["target"] == pytest.approx(100.0)
        assert budget["used"] == pytest.approx(40.0)
        assert budget["used_fraction"] == pytest.approx(0.4)

    def test_a_cycle_budget_is_the_sum_of_its_three_days(self):
        budget = self._budget(
            "2026-08-23T10:00:00Z", {date(2026, 8, 23): 40.0}, horizon="cycle"
        )

        assert budget["target"] == pytest.approx(300.0)
        assert budget["first_code"] == "MD-13"
        assert budget["last_code"] == "MD-15"

    def test_the_mission_budget_is_the_whole_ceiling(self):
        budget = self._budget(
            "2026-08-23T10:00:00Z", {date(2026, 8, 23): 40.0}, horizon="mission"
        )

        assert budget["target"] == pytest.approx(3000.0)

    def test_what_the_plan_expected_by_now_puts_an_extra_on_its_own_day(self):
        # A 300-litre run booked for MD-15, the last day of the cycle. Just
        # past midnight into that day, the plan expected the two ordinary days
        # behind us — not two thirds of a window that includes the 300.
        extras = [_extra(amount=300.0, on_date=date(2026, 8, 24))]
        budget = self._budget(
            "2026-08-23T22:10:00Z", {}, extras=extras, horizon="cycle"
        )

        assert budget["first_code"] == "MD-13"
        assert budget["target"] == pytest.approx(300.0 + 3 * 90.0)

        # Two whole days at 90, plus the sliver of MD-15 that has passed.
        assert 180.0 <= budget["planned_by_now"] < 190.0
        # And nowhere near the elapsed share of the window, which is the figure
        # a plan without a day-by-day breakdown would have had to use.
        assert budget["planned_by_now"] < budget["target"] * budget["elapsed_fraction"]

    def test_spending_faster_than_the_plan_intended_is_a_caution(self):
        # Two-thirds of the day gone, the whole allowance nearly spent.
        budget = self._budget("2026-08-23T14:00:00Z", {date(2026, 8, 23): 95.0})

        assert budget["pace_ratio"] > 1
        assert budget["status"] == track.CAUTION

    def test_spending_slower_than_the_day_passes_is_nominal(self):
        budget = self._budget("2026-08-23T14:00:00Z", {date(2026, 8, 23): 30.0})

        assert budget["status"] == track.NOMINAL

    def test_an_allowance_already_spent_is_over_whatever_the_pace_says(self):
        budget = self._budget("2026-08-23T04:00:00Z", {date(2026, 8, 23): 130.0})

        assert budget["status"] == track.OVER
        assert budget["remaining"] == pytest.approx(-30.0)

    def test_no_projection_is_published_from_the_first_minutes_of_a_window(self):
        # 00:30 local: 2% of the day gone.
        budget = self._budget("2026-08-22T22:30:00Z", {date(2026, 8, 23): 5.0})

        assert budget["projected"] is None
        assert budget["status"] == track.NOMINAL
        assert "no projection is given yet" in budget["note"]

    def test_a_window_the_sensors_missed_gets_no_verdict(self):
        budget = self._budget("2026-08-23T10:00:00Z", {})

        assert budget["status"] == track.NO_DATA
        assert budget["used"] is None

    def test_a_partly_covered_window_says_its_figure_is_a_floor(self):
        budget = self._budget(
            "2026-08-23T10:00:00Z", {date(2026, 8, 23): 40.0}, horizon="cycle"
        )

        # MD-13 elapsed with no readings; MD-14 is today and has some.
        assert budget["days_covered"] == 1
        assert budget["days_expected"] == 2
        assert "floor rather than" in budget["note"]

    def test_an_uncapped_resource_still_reports_what_was_used(self):
        budget = self._budget("2026-08-23T10:00:00Z", {date(2026, 8, 23): 40.0}, total=None)

        assert budget["status"] == track.UNSET
        assert budget["used"] == pytest.approx(40.0)
        assert budget["target"] is None


class TestPeriods:
    """The windows, and when they exist at all."""

    def test_no_mission_means_only_today(self):
        live = per.current_periods(_utc("2026-08-23T10:00:00Z"), OFFSET, pl.Mission())

        assert set(live) == {"day"}

    def test_a_declared_mission_brings_the_cycle_and_the_mission_with_it(self):
        live = per.current_periods(_utc("2026-08-23T10:00:00Z"), OFFSET, MISSION)

        assert set(live) == {"day", "cycle", "mission"}

    def test_windows_are_half_open_so_no_reading_lands_in_two(self):
        live = per.current_periods(_utc("2026-08-23T10:00:00Z"), OFFSET, MISSION)
        day = live["day"]

        assert day.end - day.start == timedelta(days=1)
        assert live["mission"].end - live["mission"].start == timedelta(days=30)

    def test_a_day_before_launch_has_no_cycle_invented_for_it(self):
        live = per.current_periods(_utc("2026-08-01T10:00:00Z"), OFFSET, MISSION)

        assert "cycle" not in live
        assert "mission" in live

    def test_elapsed_is_the_share_of_the_window_that_has_passed(self):
        live = per.current_periods(_utc("2026-08-23T10:00:00Z"), OFFSET, MISSION)

        # 12:00 local on MD-14: half a day.
        assert live["day"].elapsed_fraction == pytest.approx(0.5, abs=1e-6)

    def test_the_lookback_never_reaches_further_back_than_the_mission(self):
        assert per.clamp_to_history(START, date(2026, 8, 23), 90) == START
        assert per.clamp_to_history(START, date(2026, 8, 23), 5) == date(2026, 8, 19)


class TestEnergyPerDay:
    """A totaliser differenced into days, keyed by the habitat's calendar."""

    def _rows(self, *pairs):
        return [
            {"period_start": f"2026-08-{day:02d}T22:00:00Z", "last": value}
            for day, value in pairs
        ]

    def test_the_first_day_is_the_lead_in_and_is_not_reported(self):
        climbs = mt._climb_per_day(self._rows((19, 100.0), (20, 140.0)), OFFSET)

        # 2026-08-19T22:00Z is local midnight on the 20th.
        assert climbs == {date(2026, 8, 21): 40.0}

    def test_a_climb_spanning_a_gap_belongs_to_no_single_day(self):
        climbs = mt._climb_per_day(self._rows((19, 100.0), (22, 220.0)), OFFSET)

        assert climbs == {}

    def test_rows_arrive_in_order_however_they_were_given(self):
        climbs = mt._climb_per_day(self._rows((20, 140.0), (19, 100.0)), OFFSET)

        assert climbs == {date(2026, 8, 21): 40.0}

    def test_a_day_with_no_readings_is_counted_as_uncovered_not_as_zero(self):
        use = mt.DailyUse(per_date={date(2026, 8, 20): 40.0})
        total, missing = use.total([date(2026, 8, 20), date(2026, 8, 21)])

        assert total == 40.0
        assert missing == 1

    def test_a_window_with_nothing_in_it_has_no_total_at_all(self):
        total, missing = mt.DailyUse().total([date(2026, 8, 20)])

        assert total is None
        assert missing == 1


class TestBrief:
    """What the model is told about the plan, and what it is not told."""

    def _plan(self, **kwargs):
        fields = {
            "totals": {"water": 3000.0, "power": 1500.0},
            "sources": {"water": pl.CREW, "power": pl.CREW},
            "day_start_offset_minutes": OFFSET,
            "mission": MISSION,
        }
        fields.update(kwargs)
        return pl.Plan(**fields)  # type: ignore[arg-type]

    def test_an_undeclared_mission_tells_the_model_not_to_invent_one(self):
        text = mission_brief(self._plan(mission=pl.Mission()))

        assert "has not declared a mission" in text
        assert "must not invent a target" in text

    def test_the_brief_says_which_mission_day_it_is(self):
        text = mission_brief(self._plan(), today=date(2026, 8, 23))

        assert "Today is MD-14 of MD-30" in text
        assert "3-day cycle 5" in text

    def test_the_brief_lists_the_extras_with_the_days_they_fall_on(self):
        extras = (_extra(amount=300.0, on_date=date(2026, 8, 23), label="Algae run"),)
        text = mission_brief(self._plan(extras=extras), today=START)

        assert "Algae run" in text
        assert "MD-14" in text

    def test_the_brief_carries_no_consumption_figure_at_all(self):
        # The whole point. A used figure in the system prompt is a number the
        # model did not query, written once and stale ever after.
        text = mission_brief(self._plan(), today=date(2026, 8, 23))

        assert "get_mission_plan" in text
        for word in ("used", "consumed so far", "drew"):
            assert f"{word}:" not in text


class TestWirePayload:
    """What the service builds is what the response model declares."""

    def _tracking(self, plan: pl.Plan) -> dict:
        return track.build_tracking(plan)

    def test_the_page_envelope_declares_what_the_service_builds(self, temp_database):
        built = self._tracking(repo.load_plan())

        assert set(built) <= set(Tracking.model_fields)
        assert set(Tracking.model_fields) - set(built) == set()

    def test_a_resource_declares_what_the_service_builds(self, temp_database):
        built = self._tracking(repo.load_plan())
        row = built["resources"][0]

        assert set(row) <= set(ResourceTracking.model_fields)
        assert set(ResourceTracking.model_fields) - set(row) == set()

    def test_an_undeclared_mission_costs_no_database_round_trip(self, temp_database):
        # No mission means nothing to measure against, so nothing is measured —
        # and a habitat with no plan does not wait on Grafana to find that out.
        built = self._tracking(repo.load_plan())

        assert built["mission"]["is_declared"] is False
        assert all(row["days"] == [] for row in built["resources"])
        assert all(row["query"] == "" for row in built["resources"])

    def test_a_budget_survives_serialisation(self):
        Budget(
            horizon="day",
            label="Today",
            days=1,
            period_start="2026-08-22T22:00:00Z",
            period_end="2026-08-23T22:00:00Z",
            elapsed_fraction=0.5,
        )

    def test_a_planned_day_serialises_with_no_actual_where_there_is_none(self):
        day = PlannedDay(
            index=1,
            code="MD-01",
            date="2026-08-10",
            start="2026-08-09T22:00:00Z",
            state="future",
            planned=100.0,
        )

        assert day.actual is None
        assert day.status == "pending"


class TestCatalogue:
    def test_every_resource_in_the_plan_has_a_meter_behind_it(self):
        assert set(pl.RESOURCES) == {meter.key for meter in mt.METERS}

    def test_the_lookback_stays_inside_what_the_helpers_will_return(self):
        assert track.MAX_LOOKBACK_DAYS <= 90


class TestBucketOffset:
    """The database is asked to cut its buckets on the habitat's midnight."""

    DAY = ql.bucket_minutes("day")

    def test_no_offset_leaves_the_clause_as_it_was(self):
        assert ql.time_group(self.DAY, 0) == "time(1440m)"

    def test_the_clause_shifts_the_opposite_way_to_the_clock(self):
        # The habitat is 2h ahead, so its midnight is 22h after each UTC one.
        assert ql.time_group(self.DAY, 120) == "time(1440m, 1320m)"

    def test_a_shift_of_a_whole_bucket_is_no_shift(self):
        assert ql.time_group(ql.bucket_minutes("hour"), 120) == "time(60m)"

    def test_a_westward_offset_shifts_the_other_way(self):
        assert ql.time_group(self.DAY, -300) == "time(1440m, 300m)"

    def test_a_reading_is_filed_under_the_local_day_it_fell_in(self):
        assert tanks._period_start("2026-08-21T23:30:00Z", "day", 120) == (
            "2026-08-21T22:00:00Z"
        )

    def test_without_an_offset_the_period_is_the_utc_day(self):
        assert tanks._period_start("2026-08-21T23:30:00Z", "day", 0) == (
            "2026-08-21T00:00:00Z"
        )


class TestModelPayload:
    """What `get_mission_plan` hands the model, and what it leaves out."""

    def _long_mission(self, temp_database, days=400):
        # Started long enough ago that today is far past the cap. With the
        # mission opening on MD-01 near today, the windowing bug this guards
        # against would be invisible.
        first = repo.load_plan()
        today = per.local_date(
            datetime.now(UTC), first.day_start_offset_minutes
        )
        repo.save_mission(
            pl.Mission(name="Long haul", start=today - timedelta(days=200), days=days)
        )
        repo.save_totals({"water": 40_000.0})
        stored = repo.load_plan()
        repo.add_extra(
            pl.validate_extra(
                {"resource": "water", "label": "Dishes", "amount": 12, "kind": "daily"},
                stored.mission,
            )
        )

    def test_an_undeclared_mission_is_reported_not_papered_over(self, temp_database):
        from app.mission.query import get_mission_plan

        out = get_mission_plan()

        assert out["mission_declared"] is False
        assert "invented" in out["note"]
        assert out["resources"] == []

    def test_a_long_mission_is_windowed_rather_than_dumped(self, temp_database):
        from app.mission import query

        self._long_mission(temp_database)
        shown = query.get_mission_plan("water")["resources"][0]["days"]["shown"]

        assert len(shown) <= query.MAX_DAYS

    def test_the_window_keeps_today_even_when_every_day_carries_an_extra(
        self, temp_database
    ):
        # A daily extra marks all 400 days as interesting. Filling the cap in
        # date order would spend it on MD-01 onwards and drop the one day no
        # answer can do without.
        from app.mission import query

        self._long_mission(temp_database)
        shown = query.get_mission_plan("water")["resources"][0]["days"]["shown"]

        assert any(day["when"] == "today" for day in shown), [d["day"] for d in shown[:5]]

    def test_an_unknown_resource_is_refused_with_the_real_ones_named(
        self, temp_database
    ):
        from app.mission.query import get_mission_plan

        repo.save_mission(MISSION)
        with pytest.raises(ValueError, match="water"):
            get_mission_plan("oxygen")
