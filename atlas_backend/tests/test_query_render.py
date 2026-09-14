"""The InfluxQL renderer — the structured Query must reproduce the exact
InfluxQL the telemetry layer used to build by hand, so the Grafana/InfluxDB
path is byte-for-byte unchanged after the re-layering.
"""

from app.datasource.influx_render import render
from app.datasource.query import GroupBy, Query, Select, TagFilter, TimeWindow


class TestPointReads:
    def test_latest_is_order_desc_limit_one(self):
        q = Query(
            "Temperature",
            (Select("value"),),
            (TagFilter("Location", ("Container3",)),),
            order_desc=True,
            limit=1,
        )
        assert render(q) == (
            'SELECT "value" FROM "Temperature" '
            "WHERE \"Location\" = 'Container3' ORDER BY time DESC LIMIT 1"
        )

    def test_no_filter_omits_where(self):
        q = Query("CO2", (Select("value"),), order_desc=True, limit=1)
        assert render(q) == 'SELECT "value" FROM "CO2" ORDER BY time DESC LIMIT 1'

    def test_capitalisation_variants_become_an_or(self):
        q = Query(
            "Temperature",
            (Select("value"),),
            (TagFilter("Location", ("AirLock", "Airlock")),),
            order_desc=True,
            limit=1,
        )
        assert (
            "(\"Location\" = 'AirLock' OR \"Location\" = 'Airlock')" in render(q)
        )


class TestAggregates:
    def test_bucketed_history(self):
        q = Query(
            "Temperature",
            (Select("value", "mean"),),
            (TagFilter("Location", ("Container3",)),),
            TimeWindow("relative", minutes=60),
            GroupBy(bucket_minutes=5, fill_none=True),
        )
        assert render(q) == (
            'SELECT mean("value") FROM "Temperature" '
            "WHERE \"Location\" = 'Container3' AND time > now() - 60m "
            "GROUP BY time(5m) fill(none)"
        )

    def test_consumption_groups_by_all_tags_and_shifts_the_bucket(self):
        stats = tuple(Select("total", fn) for fn in ("first", "last", "min", "max"))
        q = Query(
            "Energy",
            stats,
            (),
            TimeWindow("relative", minutes=4320),
            GroupBy(all_tags=True, bucket_minutes=1440, offset_minutes=120),
        )
        rendered = render(q)
        assert "GROUP BY time(1440m, 1320m), * fill(none)" in rendered
        assert rendered.startswith(
            'SELECT first("total"), last("total"), min("total"), max("total")'
        )

    def test_absolute_window(self):
        q = Query(
            "Water",
            (Select("litres"),),
            (),
            TimeWindow("absolute", start="2026-08-18T05:00:00Z", end="2026-08-20T00:00:00Z"),
            order_desc=False,
            limit=1,
        )
        assert (
            "WHERE time >= '2026-08-18T05:00:00Z' AND time <= '2026-08-20T00:00:00Z'"
            in render(q)
        )
