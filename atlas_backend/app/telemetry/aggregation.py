"""Aggregation over long windows.

Two modes here, and a third that lives next door:

  summarize()       for values that are a LEVEL or RATE at an instant —
                    temperature, humidity, current, power draw, CO2.
                    mean/min/max per period.

  get_consumption() for CUMULATIVE meters that only climb — the energy
                    totaliser. Consumption is last minus first.

  tanks.get_tank_flow()
                    for a STOCK that rises and falls — a water tank. Neither
                    of the above works on one: the mean says where it tended
                    to sit and last-minus-first says only where it ended up.
                    See that module for why the two directions must not be
                    netted.

Picking the wrong one produces a number that is arithmetically correct and
answers nothing. `get_consumption` therefore verifies that its field really
does only climb, and when it does not it computes no total and says which tool
to use instead — the wrong answer here is not a crash, it is a plausible
figure nobody catches.

All arithmetic happens in Python over numbers a query returned, and the inputs
to that arithmetic are always returned alongside the result so it is
checkable.
"""


from app.datasource import get_data_source
from app.datasource.query import GroupBy, Query, Select
from app.telemetry import influxql as ql
from app.telemetry.filters import envelope, prepare_query, to_time_window

# Tag values that name an already-aggregated series (a rollup) rather than a
# real meter — summing every series would count the same energy twice. Which
# values mean "rollup" is habitat-specific (a meter that reports each phase AND
# a "Total", say), so the list lives in the habitat profile's
# `aggregate_tag_values:` section. A small always-on set covers the universal
# spellings so a habitat that declares none still avoids the obvious rollups.
_UNIVERSAL_AGGREGATE_VALUES = frozenset({"total", "all", "sum", "overall", "combined"})


def _aggregate_tag_values() -> frozenset[str]:
    from app.habitat import profile

    declared = {v.lower() for v in profile().aggregate_tag_values}
    return _UNIVERSAL_AGGREGATE_VALUES | declared


def _is_aggregate(series_tags: dict) -> bool:
    known = _aggregate_tag_values()
    return any(str(v).lower() in known for v in series_tags.values())


def summarize(
    measurement: str,
    location: str | None = None,
    field: str | None = None,
    days: float | None = None,
    group_by: str = "day",
    phase: str | None = None,
    tags: dict | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """Statistics over a window, bucketed — for RATE-style values.

    Returns mean/min/max/count per bucket plus an overall figure for the whole
    window.

    days=None (the default) covers EVERY reading on record. Pass a number only
    when the question named a period — silently narrowing an open question to
    a few days can miss the very peak it was asking about.

    Do NOT use this to total consumption from a cumulative meter; the mean of
    a rising odometer is meaningless. Use get_consumption for those.
    """
    field, filters, applied, matched, unit, source = prepare_query(
        measurement, field, location, tags, phase
    )
    bucket = ql.bucket_minutes(group_by)
    _, window_label = ql.window(days, start, end)
    win = to_time_window(days, start, end)

    stats = (Select(field, "mean"), Select(field, "min"),
             Select(field, "max"), Select(field, "count"))
    bucketed = Query(
        measurement=measurement, selects=stats, filters=tuple(filters), window=win,
        group_by=GroupBy(bucket_minutes=bucket, fill_none=True),
    )
    overall = Query(
        measurement=measurement, selects=stats, filters=tuple(filters), window=win,
    )

    source_ds = get_data_source()
    result = source_ds.run(bucketed)
    out = envelope(measurement, field, applied, matched, unit, source, result["query"])
    overall_result = source_ds.run(overall)
    out.update(
        {
            "days": days,
            "window": window_label,
            "group_by": group_by,
            "overall_query": overall_result["query"],
        }
    )

    buckets: list[dict] = []
    for _, columns, values in ql.rows(result):
        for record in ql.records(columns, values):
            if record.get("mean") is None:
                continue
            buckets.append(
                {
                    "period_start": record.get("time"),
                    "mean": round(record["mean"], 4),
                    "min": record.get("min"),
                    "max": record.get("max"),
                    "samples": record.get("count"),
                }
            )

    whole: dict | None = None
    for _, columns, values in ql.rows(overall_result):
        if not values:
            continue
        record = dict(zip(columns, values[0], strict=False))
        if record.get("mean") is not None:
            whole = {
                "mean": round(record["mean"], 4),
                "min": record.get("min"),
                "max": record.get("max"),
                "samples": record.get("count"),
            }

    # How many physical sensors were merged into those figures? Averaging
    # across sensors is usually what someone means by "the temperature in the
    # dormitory", but min/max then span every sensor, so it has to be said.
    series_probe = Query(
        measurement=measurement, selects=(Select(field, "count"),),
        filters=tuple(filters), window=win, group_by=GroupBy(all_tags=True),
    )
    probe_rows = ql.rows(source_ds.run(series_probe))
    contributing = [tags_ for tags_, _, values in probe_rows if values]
    if len(contributing) > 1:
        out["series_count"] = len(contributing)
        out["series_included"] = contributing
        out["series_note"] = (
            f"These figures merge {len(contributing)} separate series "
            "(different sensors or tags). The mean is across all of them, and "
            "min/max are the extremes of any one. Say so when reporting, or "
            "filter by tag to narrow to a single sensor."
        )

    if buckets or whole:
        kept, truncated = ql.trim_periods(buckets)
        out["data"] = {"per_period": kept, "whole_window": whole}
        if truncated:
            out["data"]["periods_total"] = len(buckets)
            out["truncated"] = (
                f"Showing the most recent {ql.MAX_PERIODS} of {len(buckets)} "
                "periods. whole_window still covers all of them."
            )
    return out


def get_consumption(
    measurement: str,
    field: str | None = None,
    location: str | None = None,
    days: float | None = None,
    group_by: str = "day",
    phase: str | None = None,
    tags: dict | None = None,
    start: str | None = None,
    end: str | None = None,
    offset_minutes: int = 0,
) -> dict:
    """Consumption over a window, from a CUMULATIVE meter.

    Every query here is GROUPed BY all tags, so each physical meter is its own
    series and its own subtraction. That matters: three electrical phases each
    keep their own totaliser, and a first()/last() across the merged set
    subtracts one meter's reading from another's, producing a large, entirely
    fictional number that still looks monotonic.

    Series whose tags mark them as already-aggregated (a Phase of "Total", for
    instance) are reported separately and EXCLUDED from the summed total —
    adding a Total to the parts it is made of double-counts the energy.

    The cumulative assumption is verified PER SERIES: if any series ever goes
    down, `cumulative` is false, no total is computed, and the deltas must not
    be reported as consumption.

    `offset_minutes` moves the bucket boundaries off UTC midnight to the local
    one — how far the habitat's clock is ahead of UTC. It changes only which
    period a reading is filed under, never the window or the total.
    """
    field, filters, applied, matched, unit, source = prepare_query(
        measurement, field, location, tags, phase
    )
    bucket = ql.bucket_minutes(group_by)
    _, window_label = ql.window(days, start, end)
    win = to_time_window(days, start, end)

    # min and max come along so the cumulative check can see INSIDE a bucket.
    # Comparing bucket endpoints alone misses a meter that dipped and
    # recovered within the day, which is exactly what a reset looks like.
    stats = (Select(field, "first"), Select(field, "last"),
             Select(field, "min"), Select(field, "max"))
    bucketed = Query(
        measurement=measurement, selects=stats, filters=tuple(filters), window=win,
        group_by=GroupBy(all_tags=True, bucket_minutes=bucket,
                         offset_minutes=offset_minutes, fill_none=True),
    )
    overall = Query(
        measurement=measurement, selects=stats, filters=tuple(filters), window=win,
        group_by=GroupBy(all_tags=True),
    )

    source_ds = get_data_source()
    result = source_ds.run(bucketed)
    out = envelope(measurement, field, applied, matched, unit, source, result["query"])
    overall_result = source_ds.run(overall)
    out.update(
        {
            "days": days,
            "window": window_label,
            "group_by": group_by,
            "overall_query": overall_result["query"],
        }
    )

    series = _per_series_periods(result)
    if not series:
        return out

    _attach_whole_window(series, overall_result)

    cumulative = all(entry["cumulative"] for entry in series)
    period_starts = {p["period_start"] for entry in series for p in entry["per_period"]}
    real = [e for e in series if not e["is_aggregate"]]
    aggregates = [e for e in series if e["is_aggregate"]]

    out["cumulative"] = cumulative
    out["series_count"] = len(series)
    out["data"] = {"series": series, "periods_counted": len(period_starts)}

    if cumulative:
        _attach_total(
            out, series, real, aggregates, period_starts, field,
            _period_basis(days, start, end, bucket, period_starts),
        )
    else:
        bad = [e for e in series if not e["cumulative"]]

        # THE NUMBERS ARE WITHHELD, not merely disclaimed.
        #
        # They used to be returned alongside a warning saying they were not
        # consumption. A reader who takes the warning at its word has no use
        # for them, and a reader who does not gets a plausible, wrong,
        # confidently-cited figure — which is the one outcome this whole
        # application exists to prevent. Observed: a model handed this result
        # reported "the clean tank fell 52.4 L, the level decreased 345.3 L"
        # as an answer, both figures being refill-minus-drawdown artefacts.
        #
        # So the deltas do not leave this function. What is left is the one
        # thing that is both true and useful: which tool does answer this.
        out["data"] = None
        out["withheld"] = (
            f"{len(series)} series were read and their per-period deltas "
            "discarded before returning."
        )
        out["warning"] = (
            f"{field} decreases in {len(bad)} of {len(series)} series, so it is "
            "not a cumulative meter. No consumption figure exists in this "
            "result and none can be derived from it."
        )
        out["redirect"] = (
            "A field that rises and falls is a LEVEL — a tank, a store, a "
            "charge state — and its two directions mean different things. "
            "Netting them describes neither. CALL get_tank_flow NOW with the "
            "same arguments: it returns how far the level fell and how far it "
            "rose, separately, which is what was actually asked. Do not "
            "answer, and do not offer to do this — do it."
        )

    if len(series) > 1:
        unconstrained = sorted(
            {k for entry in series for k in entry["tags"]} - set(applied)
        )
        if unconstrained:
            out["series_note"] = (
                f"Matched {len(series)} separate series, distinguished by "
                f"{unconstrained}. Each was subtracted on its own. Filter on "
                "those tags to narrow to one."
            )
    return out


def _per_series_periods(result: dict) -> list[dict]:
    """One entry per real series (per meter), keyed by its tag set."""
    series: list[dict] = []

    for series_tags, columns, values in ql.rows(result):
        periods = []
        for record in ql.records(columns, values):
            first, last = record.get("first"), record.get("last")
            if first is None or last is None:
                continue
            period = {
                "period_start": record.get("time"),
                "first": first,
                "last": last,
                "delta": round(last - first, 4),
            }
            # A cumulative meter never goes below where the bucket started nor
            # above where it ended. Either means it fell at some point inside
            # the bucket, which endpoint arithmetic alone cannot see.
            low, high = record.get("min"), record.get("max")
            if low is not None and high is not None and (low < first or high > last):
                period["dipped"] = True
                period["min"] = low
                period["max"] = high
            periods.append(period)
        if not periods:
            continue

        falling = [p for p in periods if p["delta"] < 0]
        dipped = [p for p in periods if p.get("dipped")]
        kept, truncated = ql.trim_periods(periods)
        entry = {
            "tags": series_tags,
            "is_aggregate": _is_aggregate(series_tags),
            "per_period": kept,
            "cumulative": not falling and not dipped,
            "periods_falling": len(falling),
            "periods_dipping": len(dipped),
            "sum_of_period_deltas": round(sum(p["delta"] for p in periods), 4),
        }
        if truncated:
            entry["periods_total"] = len(periods)
            entry["truncated"] = f"most recent {ql.MAX_PERIODS} periods shown"
        series.append(entry)

    return series


def _attach_whole_window(series: list[dict], overall: dict) -> None:
    """Add each series' whole-window endpoints, matched by tag set."""
    whole: dict[frozenset, dict] = {}
    for series_tags, columns, values in ql.rows(overall):
        if not values:
            continue
        record = dict(zip(columns, values[0], strict=False))
        if record.get("first") is None or record.get("last") is None:
            continue
        whole[frozenset(series_tags.items())] = {
            "first": record["first"],
            "last": record["last"],
            "delta": round(record["last"] - record["first"], 4),
        }

    for entry in series:
        entry["whole_window"] = whole.get(frozenset(entry["tags"].items()))


def _period_basis(
    days: float | None,
    start: str | None,
    end: str | None,
    bucket: int,
    period_starts: set,
) -> tuple[float, str]:
    """(periods to divide an average by, why) — NOT the bucket count.

    The bucket count is the trap. Buckets align to UTC midnight, so a rolling
    three-day window that starts mid-morning touches FOUR of them: one partial
    day at each end and two whole ones. Dividing a three-day total by four
    understates the daily figure by a quarter, and the result looks entirely
    reasonable, which is what makes it dangerous.

    The window's own length is the right divisor. Only when no window was
    requested at all does the data have to speak for itself.
    """
    span_days = ql.window_span_days(days, start, end)
    if span_days is None:
        return float(max(1, len(period_starts))), (
            "No window was requested, so the average divides by the "
            f"{len(period_starts)} period(s) that carry readings."
        )

    periods = span_days * 1440 / bucket
    return max(periods, 1e-9), (
        f"The average divides by the {periods:g} period(s) the requested "
        f"window spans, not by the {len(period_starts)} calendar bucket(s) it "
        "touches — buckets align to UTC midnight, so the first and last are "
        "usually partial."
    )


def _attach_total(
    out: dict,
    series: list[dict],
    real: list[dict],
    aggregates: list[dict],
    period_starts: set,
    field: str,
    basis: tuple[float, str] = (0.0, ""),
) -> None:
    """Sum the real meters, and report any rollup series as a cross-check."""
    summable = real or series  # if every series is a rollup, use them
    total = round(
        sum(
            (entry["whole_window"] or {}).get("delta", entry["sum_of_period_deltas"])
            for entry in summable
        ),
        4,
    )
    divisor, why = basis
    if divisor <= 0:
        divisor, why = float(max(1, len(period_starts))), ""

    out["data"]["total_all_series"] = total
    out["data"]["average_per_period"] = round(total / divisor, 4)
    out["data"]["periods_basis"] = round(divisor, 4)
    out["note"] = (
        f"{len(summable)} meter(s) totalled separately then summed. {why}"
    ).strip()

    if aggregates:
        out["data"]["aggregate_series"] = [
            {
                "tags": entry["tags"],
                "delta": (entry["whole_window"] or {}).get(
                    "delta", entry["sum_of_period_deltas"]
                ),
            }
            for entry in aggregates
        ]
        out["aggregate_warning"] = (
            f"{len(aggregates)} series is already a total (tag value in "
            f"{sorted(_aggregate_tag_values())}) and was EXCLUDED from "
            "total_all_series to avoid double-counting. It is reported under "
            "aggregate_series as an independent cross-check — if it disagrees "
            "with total_all_series, report both and say so."
        )
