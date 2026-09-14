"""The crew's meter log: readings in, consumption out.

No network, as with `test_mission.py` — every figure on this page is arithmetic
over a throwaway database.

The load-bearing property, asserted from several directions, is that a
DIFFERENCE between two readings is the only thing this module ever calls
consumption. Everything the page shows is a sum over those differences, so if
one block is derived from the wrong pair of readings, the day total, the
window totals and every share disagree quietly and all in the same direction.
"""

from datetime import date, timedelta

import pytest

from app.core.errors import AtlasError
from app.mission import brief
from app.mission import logbook as book
from app.mission import logquery as lq
from app.mission import plan as pl
from app.mission import repository as repo
from app.schemas.logbook import Logbook
from app.tools import registry

# A short mission, because the log's edges — the first day with no opening
# reading behind it, the last with no closing one ahead — are most of what
# there is to get wrong, and a short mission is nearly all edges.
DAYS = 5


def _plan(days: int = DAYS, start: date | None = None) -> pl.Plan:
    """A declared mission with nothing else set. The log needs no ceilings.

    Running, and ending today, so the last row of the sheet is the day the
    crew is actually standing in — which is the arrangement every edge case
    worth testing lives at.
    """
    return pl.Plan(
        totals={"water": None, "power": None},
        sources={"water": pl.DEFAULT, "power": pl.DEFAULT},
        day_start_offset_minutes=120,
        mission=pl.Mission(
            name="Reference VII",
            start=start or (date.today() - timedelta(days=days - 1)),
            days=days,
        ),
    )


def _finished(days: int = DAYS) -> pl.Plan:
    """A mission whose every day is behind us, so no round is still to come."""
    return _plan(days=days, start=date.today() - timedelta(days=days))


def _reading(meter: str, day: int, slot: str, value: float, resource: str = "power"):
    return {
        "resource": resource,
        "meter": meter,
        "day_index": day,
        "slot": slot,
        "value": value,
        "updated_at": 0.0,
    }


def _resource(payload: dict, key: str) -> dict:
    return next(item for item in payload["resources"] if item["key"] == key)


def _cell(resource: dict, meter: str, day: int, slot: str) -> dict:
    return next(
        cell
        for cell in resource["usage"]
        if cell["meter"] == meter and cell["day_index"] == day and cell["slot"] == slot
    )


def _window(resource: dict, key: str) -> dict:
    return next(window for window in resource["windows"] if window["key"] == key)


class TestTheCatalogue:
    """The dials the sheet lists, and the units they are read in."""

    def test_every_room_the_crew_walks_has_a_meter(self):
        assert [meter.key for meter in book.meters_for(book.POWER)] == [
            "test_bench_a",
            "test_bench_e",
            "test_bench_f",
            "test_bench_b",
            "test_bench_c",
            "test_bench_d",
            "test_bench_g",
        ]

    def test_every_tap_is_listed_once_and_tagged_with_its_pipe_code(self):
        codes = [meter.code for meter in book.meters_for(book.WATER)]
        assert codes == [
            "SIM-A", "SIM-B", "SIM-C", "SIM-D",
        ]
        assert len(set(codes)) == len(codes)

    def test_synthetic_outlets_keep_their_declared_streams(self):
        expected = [book.WARM, book.COLD, book.COLD, book.COLD]
        assert [meter.stream for meter in book.meters_for(book.WATER)] == expected

    def test_water_is_typed_in_cubic_metres_and_reported_in_litres(self):
        assert book.ENTRY_UNIT["water"] == "m³"
        assert book.REPORT_UNIT["water"] == "L"
        assert book.TO_REPORT["water"] == 1000.0

    def test_both_resources_are_read_on_two_rounds(self):
        # Water was read once a day at first. Two rounds on the taps buys the
        # same thing it buys on the rooms — whether the draw happened while
        # the habitat was awake or overnight — and means there is one
        # convention on the page instead of two.
        assert book.SLOTS["power"] == ("morning", "evening")
        assert book.SLOTS["water"] == ("morning", "evening")


class TestDerivingConsumption:
    """A reading is a total. Consumption is the difference between two."""

    def test_the_morning_block_runs_to_that_evenings_reading(self):
        payload = book.build_logbook(
            _plan(),
            [
                _reading("test_bench_a", 2, "morning", 1284.6),
                _reading("test_bench_a", 2, "evening", 1291.2),
            ],
        )
        cell = _cell(_resource(payload, "power"), "test_bench_a", 2, "morning")
        assert cell["status"] == book.OK
        assert cell["amount"] == pytest.approx(6.6)

    def test_the_evening_block_runs_to_the_next_mornings_reading(self):
        # The overnight hours belong to the day that ended, not to the one that
        # is starting — which is the only reading of "evening" that makes a
        # day's two blocks add up to that day's total.
        payload = book.build_logbook(
            _plan(),
            [
                _reading("test_bench_b", 2, "evening", 100.0),
                _reading("test_bench_b", 3, "morning", 104.0),
            ],
        )
        cell = _cell(_resource(payload, "power"), "test_bench_b", 2, "evening")
        assert cell["status"] == book.OK
        assert cell["amount"] == pytest.approx(4.0)
        assert cell["closes_code"] == "MD-03"

    def test_a_days_total_is_this_morning_to_the_next_morning(self):
        payload = book.build_logbook(
            _plan(),
            [
                _reading("test_bench_b", 2, "morning", 100.0),
                _reading("test_bench_b", 2, "evening", 106.0),
                _reading("test_bench_b", 3, "morning", 110.0),
            ],
        )
        power = _resource(payload, "power")
        day = next(item for item in power["days"] if item["index"] == 2)
        assert day["total"] == pytest.approx(10.0)

    def test_water_is_converted_to_litres_on_the_way_out(self):
        payload = book.build_logbook(
            _plan(),
            [
                _reading("demo_warm", 1, "morning", 12.0184, "water"),
                _reading("demo_warm", 1, "evening", 12.0368, "water"),
            ],
        )
        cell = _cell(_resource(payload, "water"), "demo_warm", 1, "morning")
        assert cell["amount"] == pytest.approx(18.4)

    def test_the_last_logged_day_is_open_rather_than_a_quiet_day(self):
        # Nothing closes it yet. Reporting zero here would draw a collapse in
        # consumption every morning before the rounds are walked.
        payload = book.build_logbook(
            _plan(), [_reading("test_bench_a", DAYS, "morning", 50.0)]
        )
        power = _resource(payload, "power")
        cell = _cell(power, "test_bench_a", DAYS, "morning")
        assert cell["status"] == book.OPEN
        assert cell["amount"] is None

    def test_a_block_the_mission_ends_before_can_never_close(self):
        # MD-05's evening runs into an MD-06 this mission does not have. It is
        # open forever, and it is not the crew's to fill in.
        payload = book.build_logbook(
            _finished(), [_reading("test_bench_a", DAYS, "evening", 50.0)]
        )
        cell = _cell(_resource(payload, "power"), "test_bench_a", DAYS, "evening")
        assert cell["status"] == book.OPEN
        assert cell["closes_code"] is None

    def test_a_round_that_happened_and_was_not_written_down_is_a_gap(self):
        # Both ends of this block are in the past, so somebody missed it —
        # which asks for a different action than waiting.
        payload = book.build_logbook(
            _finished(),
            [
                _reading("test_bench_a", 1, "morning", 10.0),
                _reading("test_bench_a", 3, "morning", 30.0),
            ],
        )
        power = _resource(payload, "power")
        assert _cell(power, "test_bench_a", 1, "morning")["status"] == book.GAP

    def test_a_meter_that_counts_down_is_refused_rather_than_averaged_in(self):
        payload = book.build_logbook(
            _plan(),
            [
                _reading("test_bench_d", 1, "morning", 500.0),
                _reading("test_bench_d", 1, "evening", 400.0),
            ],
        )
        power = _resource(payload, "power")
        cell = _cell(power, "test_bench_d", 1, "morning")
        assert cell["status"] == book.BACKWARDS
        assert cell["amount"] is None
        assert power["issues"], "a backwards meter has to be said out loud"

    def test_the_mission_total_is_the_sum_of_every_block(self):
        readings = []
        for day in range(1, DAYS + 1):
            readings.append(_reading("test_bench_a", day, "morning", 100.0 + day * 10))
            readings.append(_reading("test_bench_a", day, "evening", 105.0 + day * 10))

        payload = book.build_logbook(_plan(), readings)
        power = _resource(payload, "power")
        window = _window(power, "mission")

        blocks = sum(
            cell["amount"] for cell in power["usage"] if cell["amount"] is not None
        )
        # Five morning blocks of 5, and four evening blocks of 5 — MD-05's
        # evening has no MD-06 morning to close it.
        assert window["total"] == pytest.approx(blocks)
        assert window["total"] == pytest.approx(45.0)


class TestTheWindows:
    """Today, the last three days, and the whole mission — off one array."""

    def _rounds(self, days: int = DAYS):
        """Both rounds, every day, for two rooms.

        Test bench A draws 10 a day and the test_bench_b 5, split evenly across the two
        blocks — so the shares are 2:1 in every window, which is the property
        the share assertions are actually about.
        """
        readings = []
        for day in range(1, days + 1):
            readings.append(_reading("test_bench_a", day, "morning", day * 10.0))
            readings.append(_reading("test_bench_a", day, "evening", day * 10.0 + 5.0))
            readings.append(_reading("test_bench_b", day, "morning", day * 5.0))
            readings.append(_reading("test_bench_b", day, "evening", day * 5.0 + 2.5))
        return readings

    def test_a_window_ends_at_the_last_logged_day_not_at_today(self):
        # Ten mission days, all of them behind us, and rounds walked for only
        # the first three. The day window is MD-03 — not MD-10, which would
        # report the habitat as having drawn nothing at all.
        payload = book.build_logbook(_finished(days=10), self._rounds(days=3))
        power = _resource(payload, "power")

        assert power["latest_day"] == 3
        assert _window(power, "day")["last_code"] == "MD-03"
        assert _window(power, "day")["total"] is not None

    def test_the_day_window_covers_exactly_one_day(self):
        payload = book.build_logbook(_plan(), self._rounds())
        window = _window(_resource(payload, "power"), "day")
        assert window["days_in_window"] == 1
        # MD-05's morning block closes on its own evening round; its evening
        # block waits on an MD-06 morning that has not happened.
        assert (window["first_code"], window["last_code"]) == ("MD-05", "MD-05")
        assert window["total"] == pytest.approx(7.5)
        assert window["complete"] is False

    def test_the_three_day_window_covers_three_and_stops_at_MD_01(self):
        payload = book.build_logbook(_plan(), self._rounds())
        window = _window(_resource(payload, "power"), "last3")
        assert (window["first_code"], window["last_code"]) == ("MD-03", "MD-05")
        assert window["total"] == pytest.approx(15.0 + 15.0 + 7.5)

    def test_the_three_day_window_cannot_reach_back_past_MD_01(self):
        payload = book.build_logbook(_plan(), self._rounds(days=2))
        window = _window(_resource(payload, "power"), "last3")
        assert window["first_code"] == "MD-01"
        assert window["days_in_window"] == 2

    def test_shares_are_fractions_of_that_windows_own_total(self):
        payload = book.build_logbook(_plan(), self._rounds())
        window = _window(_resource(payload, "power"), "mission")
        shares = {row["key"]: row for row in window["meters"]}
        assert shares["test_bench_a"]["share"] == pytest.approx(2 / 3)
        assert shares["test_bench_b"]["share"] == pytest.approx(1 / 3)
        assert sum(row["amount"] for row in window["meters"]) == pytest.approx(
            window["total"]
        )

    def test_a_room_with_nothing_logged_is_listed_at_zero_not_left_out(self):
        # An absence in a ranked list reads as "not metered here", which is a
        # different and wrong claim.
        payload = book.build_logbook(_plan(), self._rounds())
        window = _window(_resource(payload, "power"), "mission")
        assert len(window["meters"]) == len(book.meters_for(book.POWER))
        test_bench_e = next(row for row in window["meters"] if row["key"] == "test_bench_e")
        assert test_bench_e["amount"] == 0.0 and test_bench_e["logged"] is False

    def test_an_empty_log_reports_no_total_rather_than_zero(self):
        payload = book.build_logbook(_plan(), [])
        for resource in payload["resources"]:
            for window in resource["windows"]:
                assert window["total"] is None
                assert all(row["share"] is None for row in window["meters"])

    def test_water_collapses_onto_what_it_serves_and_onto_temperature(self):
        readings = []
        for day in (1, 2):
            for meter, rate in (
                ("demo_warm", 1.0),
                ("demo_cold", 3.0),
                ("demo_sink", 1.0),
            ):
                # Half the day's draw in each block, so the totals are the
                # same as they were when water was read once a day.
                readings.append(
                    _reading(meter, day, "morning", day * rate, "water")
                )
                readings.append(
                    _reading(meter, day, "evening", day * rate + rate / 2, "water")
                )

        payload = book.build_logbook(_plan(), readings)
        window = _window(_resource(payload, "water"), "mission")

        # Three blocks close: both of MD-01 and MD-02's morning. Each block is
        # half that meter's daily rate, so each meter contributes 1.5 x rate.
        groups = {row["key"]: row["amount"] for row in window["groups"]}
        assert groups["shower"] == pytest.approx(6000.0)   # (1.0 + 3.0) x 1.5
        assert groups["test_bench_a"] == pytest.approx(1500.0)  # 1.0 x 1.5

        streams = {row["key"]: row["amount"] for row in window["streams"]}
        assert streams["warm"] == pytest.approx(1500.0)
        assert streams["cold"] == pytest.approx(6000.0)
        assert sum(streams.values()) == pytest.approx(window["total"])

    def test_morning_and_evening_split_the_days_power(self):
        payload = book.build_logbook(
            _plan(),
            [
                _reading("test_bench_b", 1, "morning", 0.0),
                _reading("test_bench_b", 1, "evening", 8.0),
                _reading("test_bench_b", 2, "morning", 10.0),
            ],
        )
        window = _window(_resource(payload, "power"), "mission")
        slots = {row["key"]: row["amount"] for row in window["slots"]}
        assert slots["morning"] == pytest.approx(8.0)
        assert slots["evening"] == pytest.approx(2.0)


class TestTheSheet:
    """What is laid out for the crew to write into."""

    def test_the_sheet_has_a_row_for_every_planned_mission_day(self):
        payload = book.build_logbook(_plan(days=14), [])
        assert len(payload["days"]) == 14
        assert payload["days"][0]["code"] == "MD-01"
        assert payload["days"][-1]["code"] == "MD-14"

    def test_a_longer_mission_gets_a_longer_sheet(self):
        assert len(book.build_logbook(_plan(days=30), [])["days"]) == 30

    def test_no_mission_means_no_sheet_rather_than_a_guess(self):
        plan = pl.Plan(
            totals={},
            sources={},
            day_start_offset_minutes=0,
            mission=pl.Mission(),
        )
        payload = book.build_logbook(plan, [])
        assert payload["mission"]["is_declared"] is False
        assert payload["days"] == []

    def test_coverage_counts_rounds_that_have_happened_separately(self):
        # Judging a crew against boxes for days that have not arrived yet would
        # report every mission as 90% unlogged on MD-01.
        plan = _plan(days=10, start=date.today() - timedelta(days=2))
        payload = book.build_logbook(plan, [_reading("test_bench_a", 1, "morning", 5.0)])
        coverage = _resource(payload, "power")["coverage"]

        assert coverage["total"] == len(book.meters_for(book.POWER)) * 10 * 2
        assert coverage["expected"] == len(book.meters_for(book.POWER)) * 2 * 2
        assert coverage["filled"] == 1
        assert coverage["expected_filled"] == 1


class TestRefusals:
    """What the sheet will not accept, and what it says about it."""

    def test_an_unknown_dial_is_refused(self):
        with pytest.raises(AtlasError, match="no power meter called"):
            book.check_meter("power", "airlock")

    def test_water_is_now_filed_against_the_same_rounds_as_power(self):
        assert book.check_slot("water", "morning") == "morning"
        assert book.check_slot("water", "evening") == "evening"

    def test_a_round_that_is_not_walked_is_refused(self):
        with pytest.raises(AtlasError, match="morning and evening"):
            book.check_slot("water", "midnight")

    def test_a_day_outside_the_mission_is_refused_by_name(self):
        with pytest.raises(AtlasError, match="MD-01 to MD-05"):
            book.check_day(9, _plan().mission)

    def test_a_reading_needs_a_mission_to_be_filed_against(self):
        with pytest.raises(AtlasError, match="No mission has been declared"):
            book.check_day(1, pl.Mission())

    def test_a_negative_reading_is_refused_because_a_dial_counts_up(self):
        with pytest.raises(AtlasError, match="counts up from zero"):
            book.check_value(-4, book.meters_for(book.POWER)[0])

    def test_a_wildly_large_reading_names_the_unit_it_expected(self):
        with pytest.raises(AtlasError, match="m³"):
            book.check_value(1e12, book.meters_for(book.WATER)[0])

    def test_an_empty_box_is_a_withdrawal_not_a_zero(self):
        assert book.check_value("", book.meters_for(book.POWER)[0]) is None
        assert book.check_value(None, book.meters_for(book.POWER)[0]) is None


class TestStorage:
    """The log on disk."""

    def test_a_reading_survives_a_round_trip(self, temp_database):
        repo.save_reading("power", "test_bench_a", 3, "morning", 1284.6)
        assert repo.load_readings() == [
            {
                "resource": "power",
                "meter": "test_bench_a",
                "day_index": 3,
                "slot": "morning",
                "value": 1284.6,
                "updated_at": pytest.approx(
                    repo.load_readings()[0]["updated_at"]
                ),
            }
        ]

    def test_writing_the_same_box_twice_corrects_it(self, temp_database):
        repo.save_reading("power", "test_bench_a", 3, "morning", 1284.6)
        repo.save_reading("power", "test_bench_a", 3, "morning", 1285.0)
        rows = repo.load_readings()
        assert len(rows) == 1 and rows[0]["value"] == 1285.0

    def test_clearing_a_box_removes_only_that_box(self, temp_database):
        repo.save_reading("power", "test_bench_a", 3, "morning", 10.0)
        repo.save_reading("power", "test_bench_a", 3, "evening", 12.0)
        repo.delete_reading("power", "test_bench_a", 3, "morning")
        assert [row["slot"] for row in repo.load_readings()] == ["evening"]

    def test_resetting_the_mission_plan_does_not_delete_the_crews_readings(
        self, temp_database
    ):
        # The dial said what it said. Re-declaring a mission does not make a
        # reading somebody walked the habitat to take untrue.
        repo.save_reading("water", "demo_wash", 1, "morning", 3.2)
        repo.reset_plan()
        assert len(repo.load_readings()) == 1

    def test_clearing_the_log_is_its_own_deliberate_action(self, temp_database):
        repo.save_reading("water", "demo_wash", 1, "morning", 3.2)
        repo.save_reading("power", "test_bench_b", 1, "morning", 8.0)
        repo.clear_readings("water")
        assert [row["resource"] for row in repo.load_readings()] == ["power"]
        repo.clear_readings()
        assert repo.load_readings() == []


class TestTheContract:
    """The payload the browser is actually handed."""

    def test_the_whole_payload_validates_against_the_response_model(self):
        readings = [
            _reading("test_bench_a", 1, "morning", 10.0),
            _reading("test_bench_a", 1, "evening", 16.0),
            _reading("test_bench_a", 2, "morning", 20.0),
            _reading("demo_warm", 1, "morning", 1.0, "water"),
            _reading("demo_warm", 1, "evening", 1.5, "water"),
        ]
        payload = Logbook(**book.build_logbook(_plan(), readings))

        power = next(item for item in payload.resources if item.key == "power")
        assert power.unit == "kWh"
        assert power.days[0].total == pytest.approx(10.0)

        water = next(item for item in payload.resources if item.key == "water")
        assert water.entry_unit == "m³" and water.unit == "L"
        assert water.days[0].total == pytest.approx(500.0)


class TestTheAssistantsView:
    """The log as the model reads it, through `get_crew_meter_log`.

    The tool's job is not only to carry the figures. It is to carry them
    STAMPED — a result the model cannot mistake for telemetry, because the one
    failure that matters here is an answer that quietly presents a hand-read
    dial as a sensor reading, or adds the two accounts together.
    """

    def _logged(self, temp_database, days: int = DAYS):
        repo.save_mission(_plan(days=days).mission)
        for day in range(1, days + 1):
            repo.save_reading("power", "test_bench_a", day, "morning", day * 10.0)
            repo.save_reading("power", "test_bench_a", day, "evening", day * 10.0 + 5.0)
            repo.save_reading("power", "test_bench_b", day, "morning", day * 5.0)
            repo.save_reading("power", "test_bench_b", day, "evening", day * 5.0 + 2.5)
            repo.save_reading("water", "demo_warm", day, "morning", day * 0.1)
            repo.save_reading(
                "water", "demo_warm", day, "evening", day * 0.1 + 0.05
            )

    def test_it_says_where_the_figures_came_from(self, temp_database):
        self._logged(temp_database)
        result = lq.get_crew_meter_log()

        assert result["source"] == "crew_meter_log"
        assert "NOT from the habitat database" in result["source_note"]
        assert any("never average" in note.lower() for note in result["reading_notes"])

    def test_it_reports_per_room_totals_and_shares(self, temp_database):
        self._logged(temp_database)
        power = next(
            row
            for row in lq.get_crew_meter_log(resource="power")["resources"]
            if row["resource"] == "power"
        )
        window = next(w for w in power["windows"] if w["window"].startswith("Since"))

        rooms = {row["name"]: row for row in window["by_room"]}
        assert rooms["Test bench A"]["share_pct"] == pytest.approx(66.7, abs=0.1)
        assert rooms["Test bench B"]["share_pct"] == pytest.approx(33.3, abs=0.1)

    def test_water_reaches_the_model_in_litres(self, temp_database):
        self._logged(temp_database)
        water = next(
            row
            for row in lq.get_crew_meter_log(resource="water")["resources"]
            if row["resource"] == "water"
        )
        assert water["unit"] == "L"
        assert water["read_off_the_dial_in"] == "m³"
        # 0.1 m3 a day is 100 litres a day, never 0.1 of anything.
        assert water["days"][0]["total"] == pytest.approx(100.0)

    def test_a_tap_can_be_named_by_its_pipe_code(self, temp_database):
        self._logged(temp_database)
        # "How much does SIM-A use" is how a crew member actually asks.
        result = lq.get_crew_meter_log(resource="water", meter="SIM-A")
        row = result["resources"][0]
        assert row["filtered_to_one_meter"] == "Test warm outlet"
        assert len(row["that_meters_days"]) > 0

    def test_a_room_can_be_named_the_way_a_person_says_it(self, temp_database):
        self._logged(temp_database)
        row = lq.get_crew_meter_log(resource="power", meter="Test bench A")["resources"][0]
        assert row["filtered_to_one_meter"] == "Test bench A"

    def test_an_unknown_meter_is_refused_with_the_real_list(self, temp_database):
        self._logged(temp_database)
        # A ValueError the registry turns into a correction the model can act
        # on in one more round, rather than a dead end it reports as an outage.
        with pytest.raises(ValueError, match="Test bench A"):
            lq.get_crew_meter_log(meter="the airlock")

    def test_one_day_can_be_broken_out_block_by_block(self, temp_database):
        self._logged(temp_database)
        row = lq.get_crew_meter_log(resource="power", mission_day=2)["resources"][0]
        blocks = row["MD-02_block_by_block"]

        test_bench_a = [b for b in blocks if b["meter"] == "Test bench A"]
        # Named for the consumption, not for the round that opened it — the
        # same words the page uses, so an answer and the log agree.
        assert {b["block"] for b in test_bench_a} == {"daytime", "overnight"}
        assert sum(b["amount"] for b in test_bench_a) == pytest.approx(10.0)

    def test_a_day_outside_the_mission_is_refused_by_name(self, temp_database):
        self._logged(temp_database)
        with pytest.raises(ValueError, match="MD-01 to MD-05"):
            lq.get_crew_meter_log(mission_day=99)

    def test_an_open_day_is_flagged_so_it_is_never_quoted_as_a_total(
        self, temp_database
    ):
        self._logged(temp_database)
        row = lq.get_crew_meter_log(resource="power")["resources"][0]
        last = row["days"][-1]
        assert last["day"] == f"MD-{DAYS:02d}"
        assert last["still_open"] is True

    def test_rooms_with_nothing_logged_are_named_as_gaps(self, temp_database):
        self._logged(temp_database)
        row = lq.get_crew_meter_log(resource="power")["resources"][0]
        # Five of the seven rooms were never walked. That is a hole in the
        # record, and the model has to be able to say so rather than report
        # the habitat as a two-room habitat.
        assert "Test bench E" in row["meters_with_nothing_logged"]
        assert "Test bench A" not in row["meters_with_nothing_logged"]

    def test_with_no_mission_it_says_so_instead_of_returning_figures(
        self, temp_database
    ):
        result = lq.get_crew_meter_log()
        assert result["mission_declared"] is False
        assert result["resources"] == []

    def test_it_is_registered_as_a_tool_the_model_can_call(self):
        assert "get_crew_meter_log" in registry.TOOL_FUNCTIONS
        schema = next(
            item
            for item in registry.schemas()
            if item["name"] == "get_crew_meter_log"
        )
        # The description has to carry the one thing no other tool can do, or
        # the model will never reach for it — and the one thing it must not do.
        assert "ONLY SOURCE" in schema["description"]
        assert "never add" in schema["description"].lower()


class TestTheBrief:
    """What the system prompt says about the log — and what it must not."""

    def test_it_never_puts_a_consumption_figure_in_the_prompt(self):
        plan = _plan()
        text = brief.crew_log_brief(plan, {"power": 70, "water": 55})

        assert "125 readings are on record" in text
        assert "get_crew_meter_log" in text
        # A count is a fact about the record. A litre figure would be a
        # measurement the model never queried.
        for forbidden in ("kWh", "litres", "L a day"):
            assert forbidden not in text

    def test_an_empty_log_forbids_estimating_a_room_split(self):
        text = brief.crew_log_brief(_plan(), {})
        assert "Nothing has been logged yet" in text
        assert "must not estimate" in text

    def test_no_mission_means_no_section_at_all(self):
        assert brief.crew_log_brief(_plan_undeclared(), {"power": 4}) == ""


def _plan_undeclared() -> pl.Plan:
    return pl.Plan(
        totals={}, sources={}, day_start_offset_minutes=0, mission=pl.Mission()
    )


class TestTheWaterMigration:
    """Water readings taken when water was read once a day.

    The round they were filed against no longer exists. A row left on it would
    still be on disk and on no sheet — invisible, and silently absent from
    every total — which is the worst of the three possible outcomes.
    """

    def _legacy(self, meter: str, day: int, value: float) -> None:
        """Write a row the way the old single-round sheet wrote it."""
        from app.storage.database import connect

        with connect() as connection:
            connection.execute(
                """
                INSERT INTO mission_readings
                    (resource, meter, day_index, slot, value, updated_at)
                VALUES ('water', ?, ?, 'daily', ?, 0.0)
                """,
                (meter, day, value),
            )

    def test_an_old_daily_reading_is_lifted_onto_the_morning_round(
        self, temp_database
    ):
        from app.storage.database import initialise

        self._legacy("demo_wash", 2, 9.15)
        initialise()

        rows = repo.load_readings()
        assert [(row["slot"], row["value"]) for row in rows] == [("morning", 9.15)]

    def test_a_lifted_day_is_a_gap_until_its_evening_round_is_walked(
        self, temp_database
    ):
        from app.storage.database import initialise

        self._legacy("demo_wash", 1, 9.0)
        self._legacy("demo_wash", 2, 9.5)
        initialise()

        payload = book.build_logbook(_finished(), repo.load_readings())
        # Every block spans a morning to an evening or an evening to a morning,
        # so readings that are all on one round close nothing. The honest
        # report is a gap: nobody walked an evening round on those days, and
        # inventing a split between day and night to preserve the total would
        # be a claim about hours nobody measured.
        assert _cell(_resource(payload, "water"), "demo_wash", 1, "morning")[
            "status"
        ] == book.GAP

    def test_a_lifted_reading_derives_once_the_evening_is_filled_in(
        self, temp_database
    ):
        from app.storage.database import initialise

        self._legacy("demo_wash", 1, 9.0)
        initialise()
        repo.save_reading("water", "demo_wash", 1, "evening", 9.5)

        payload = book.build_logbook(_plan(), repo.load_readings())
        cell = _cell(_resource(payload, "water"), "demo_wash", 1, "morning")
        assert cell["amount"] == pytest.approx(500.0)

    def test_it_never_overwrites_a_reading_the_crew_has_since_entered(
        self, temp_database
    ):
        from app.storage.database import initialise

        repo.save_reading("water", "demo_wash", 2, "morning", 12.0)
        self._legacy("demo_wash", 2, 9.15)
        initialise()

        rows = repo.load_readings()
        # The newer figure is the one entered on the current sheet. The
        # stranded old row goes rather than clobbering it.
        assert [(row["slot"], row["value"]) for row in rows] == [("morning", 12.0)]

    def test_running_it_twice_changes_nothing(self, temp_database):
        from app.storage.database import initialise

        self._legacy("demo_wash", 2, 9.15)
        initialise()
        initialise()
        assert len(repo.load_readings()) == 1


class TestNamingTheBlocks:
    """A round and the block it opens are two different things.

    One name for both is the mistake this page invites, and it is not a
    cosmetic one: a bar labelled "Morning round" reads as the reading taken in
    the morning, rather than as everything drawn between that round and the
    next. These assertions are what stop the two names collapsing back into
    one the next time somebody tidies the labels.
    """

    def test_the_round_and_the_block_have_different_names(self):
        assert book.SLOT_LABEL["morning"] == "Morning round"
        assert book.BLOCK_LABEL["morning"] == "Daytime"
        assert book.SLOT_LABEL["evening"] == "Evening round"
        assert book.BLOCK_LABEL["evening"] == "Overnight"

    def test_every_slot_carries_both_names_and_its_span(self):
        payload = book.build_logbook(_plan(), [])
        slots = _resource(payload, "power")["slots"]

        assert [slot["label"] for slot in slots] == ["Morning round", "Evening round"]
        assert [slot["block_label"] for slot in slots] == ["Daytime", "Overnight"]
        # The span is the whole answer to "when is this one calculated", and
        # the evening one is the answer that surprises people.
        assert "next morning" in slots[1]["covers"]

    def test_the_day_night_split_is_labelled_by_the_block_not_the_round(self):
        payload = book.build_logbook(
            _plan(),
            [
                _reading("test_bench_b", 1, "morning", 0.0),
                _reading("test_bench_b", 1, "evening", 8.0),
                _reading("test_bench_b", 2, "morning", 10.0),
            ],
        )
        window = _window(_resource(payload, "power"), "mission")
        split = {row["label"]: row["amount"] for row in window["slots"]}

        assert split == {"Daytime": pytest.approx(8.0), "Overnight": pytest.approx(2.0)}
        assert all(row["covers"] for row in window["slots"])
