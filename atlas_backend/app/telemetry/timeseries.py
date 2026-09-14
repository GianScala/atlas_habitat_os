"""Bucketed multi-series queries, for charting.

The chat tools answer a question. This answers "draw me the last N hours",
which needs a different shape: one row per bucket per series, sized so a chart
gets roughly 100–150 points however wide the window is.

Three aggregation modes, because the habitat has three kinds of number:

  mean       a level or rate at an instant — temperature, power draw, CO2.
  delta      net change per bucket, for a cumulative meter or a tank level.
             Signed: a tank being refilled shows positive.
  drawdown   how much a falling level fell, per bucket. Consumption from a
             supply tank, where a rise is a refill rather than negative use.

A change is measured BETWEEN buckets, not inside one: the level a bucket
settles at, minus the level the bucket before it settled at. Measuring inside
a bucket instead loses every change that happens across a bucket boundary —
and where a bucket holds a single reading, as a one-minute bucket does for a
sensor that writes once a minute, it loses all of them and reports a flat
zero. That is also why the query reaches one bucket further back than the
window asks for: the first bucket on the chart needs a reading to be a change
from, and inventing one is not an option.

Every mode aggregates with mean(). A level chart and a consumption chart built
from the same field have to agree, and they cannot if one reads the bucket's
average and the other reads whichever single sample landed last. Where a
bucket holds several readings the average is also the quieter estimate, which
matters a great deal to the change modes — see below.

DEADBAND. Differencing a level amplifies its noise, and `drawdown` then makes
that noise one-sided: it keeps every downward wobble as use and discards every
upward one as a refill, so a tank that is not moving at all still reports
steady consumption that never falls to zero. The fix is a deadband, applied
with hysteresis against a held REFERENCE level rather than against the
previous bucket. Thresholding each step in isolation would be worse than
useless — a genuine slow drain moves less per bucket than the noise does, so a
per-step threshold large enough to reject the noise erases the very signal the
chart exists to show. Measured against a reference that only moves when the
level truly departs from it, noise oscillates below the threshold forever and
reports nothing, while a slow drain accumulates across buckets until it
crosses and is reported in full.

The cost is a bounded lag: consumption still sitting below the threshold when
the window ends is not yet attributed, so a total can undercount by up to one
deadband. Undercounting by a known bound beats reporting use that never
happened.

THE SEED. Holding a reference makes every bar downstream of it relative to
where that reference started, so the level the FIRST one is set from decides
what the whole window reports. Set from a single lead-in bucket, that is one
raw sample whenever a bucket holds one — which is every range down to 1-minute
buckets — and the gauge's dither lands whole on the chart. Measured on the
clean water tank at 22:50 on 2026-08-21, the same bar read anywhere from 2.3 L
to 3.2 L depending only on which minute the window happened to open, against a
fall that was really 3.5 L. Two ranges of the same dashboard disagreed about
the same minute, which is the clearest possible sign the number was not a
property of that minute.

So the reference is seeded from several buckets rather than one — see
`_seed_reference` — enough of them to cover SEED_MINUTES of gauge however
short the buckets are. Where the tank is still, their median is the level; a
median rather than a mean because a spike at the very start has no neighbour
on its left and so is the one excursion `_reject_spikes` cannot see. Where the
tank is already moving when the window opens, a median would sit behind the
level and charge the lag to the first bar, so the last lead-in reading is used
instead — mid-movement, the most recent reading is the honest anchor.

SPIKES. The deadband answers a gauge that wobbles; it does not answer a gauge
that reports one bad bucket. A lone reading well below its neighbours clears
the threshold, so `drawdown` charges the whole plunge as use and then writes
the recovery off as a refill — the same movement billed twice — and a lone
reading ABOVE its neighbours does the same thing in the other order, banking
a phantom refill and charging the fall back to reality as use. Short buckets
make this the dominant error: a 2-minute bucket holds two samples, so one bad
sample moves it by half its own error, while the noise floors in
`instruments.py` were measured over 30- and 60-minute buckets. On a real three
hours of the clean water tank it reported 46.2 L drawn from a tank that had
fallen 38.5 L, one 8.8 L bar of it from a single two-minute dip.

So one-bucket excursions are rejected before anything is differenced — see
`_reject_spikes`. Water does not leave a tank and come back within a bucket.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.core.errors import QueryError
from app.datasource import get_data_source
from app.datasource.query import GroupBy, Query, Select, TagFilter, TimeWindow
from app.telemetry import influxql as ql
from app.telemetry.units import unit_for

# range key -> (window in minutes, bucket in minutes)
#
# Bucket sizes aim at 100–150 points: enough to show shape, few enough that
# the payload stays small and the chart stays legible.
RANGES: dict[str, tuple[int, int]] = {
    "30m": (30, 1),
    "1h": (60, 1),
    "3h": (180, 2),
    "5h": (300, 3),
    "12h": (720, 5),
    "24h": (1440, 10),
    "48h": (2880, 20),
    "72h": (4320, 30),
    "5d": (7200, 60),
    "7d": (10080, 60),
    "14d": (20160, 180),
}

RANGE_LABELS: dict[str, str] = {
    "30m": "30 min",
    "1h": "1 hour",
    "3h": "3 hours",
    "5h": "5 hours",
    "12h": "12 hours",
    "24h": "24 hours",
    "48h": "48 hours",
    "72h": "72 hours",
    "5d": "5 days",
    "7d": "7 days",
    "14d": "14 days",
}

# --------------------------------------------------------------------------
# A window the reader picked the start of
#
# The presets all end now and are measured backwards from it. "Since 08:00 on
# the 20th" cannot be: it is an instant, and the distance from it to now grows
# while you look at it. So a custom window carries its start and the query is
# pinned to that instant rather than to a rolling offset — otherwise every
# refetch would quietly show a slightly different window than the one asked
# for, and two panels fetched a second apart would not begin at the same place.
#
# It rides in the same `range` string as a preset, as `since:<ISO instant>`.
# That is deliberate: the range key is also the browser's cache key, the
# remembered choice, and the thing the payload echoes back so a page can tell
# whether the chart on screen is the window that is currently selected. One
# kind of key means all of that machinery carries a custom window unchanged.
# --------------------------------------------------------------------------

CUSTOM_PREFIX = "since:"

# Under five minutes there is nothing to draw — and for a change mode, not
# enough lead-in to difference against. Over ninety days the reader wants the
# mission history, not a panel of 1-day buckets.
MIN_CUSTOM_MINUTES = 5
MAX_CUSTOM_MINUTES = 90 * 1440

# Past the longest preset there is no preset to follow, so the ladder carries
# on from it. Only spans longer than 14 days ever reach this.
BUCKET_LADDER = (60, 120, 180, 360, 720, 1440)

# What that ladder is chosen against, and roughly what the presets themselves
# hold to: 24 h at 10-minute buckets is 144 points, and so is 48 h at 20.
TARGET_POINTS = 144


@dataclass(frozen=True)
class Window:
    """The stretch of time a chart covers, however it was asked for."""

    # Exactly the string the caller passed, echoed rather than normalised: the
    # browser compares it against the filter it has selected to decide whether
    # the chart on screen is still the answer to the current question.
    key: str
    label: str
    minutes: int
    bucket_minutes: int
    # The instant the window opens, for a custom one. None for a preset, which
    # opens `minutes` before whenever it is asked.
    start: str | None = None


def _bucket_for(minutes: int) -> int:
    """The resolution a span of this length is drawn at.

    Read off the presets rather than computed independently: a custom window
    is drawn like the shortest preset that would contain it. That is not just
    tidiness — the preset bucket sizes are hand-picked and do not all follow
    one formula (7 days keeps the 60-minute buckets of 5 days rather than
    halving the point count), and a custom window of exactly seven days that
    disagreed with the 7d preset about the same week would be two answers to
    one question.
    """
    for window_minutes, bucket in RANGES.values():
        if minutes <= window_minutes:
            return bucket

    # Longer than any preset. Keep going on the ladder.
    for bucket in BUCKET_LADDER:
        if minutes / bucket <= TARGET_POINTS:
            return bucket
    return BUCKET_LADDER[-1]


def _custom_window(range_key: str) -> Window:
    """Parse `since:<ISO instant>` into a window running up to now."""
    raw = range_key[len(CUSTOM_PREFIX) :].strip()
    if not raw:
        raise QueryError(
            "A custom window needs a start, as "
            f"'{CUSTOM_PREFIX}2026-08-20T14:00:00Z'."
        )

    try:
        start = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise QueryError(
            f"Not an ISO 8601 instant: {raw!r}. Use e.g. "
            f"'{CUSTOM_PREFIX}2026-08-20T14:00:00Z'."
        ) from exc

    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    start = start.astimezone(UTC)

    minutes = int((datetime.now(UTC) - start).total_seconds() // 60)

    if minutes < 0:
        raise QueryError(
            "That start is in the future. A window runs from a moment that "
            "has already happened up to now."
        )
    if minutes < MIN_CUSTOM_MINUTES:
        raise QueryError(
            f"That start is {minutes} minutes ago, which is too recent to "
            f"chart. Pick one at least {MIN_CUSTOM_MINUTES} minutes back."
        )
    if minutes > MAX_CUSTOM_MINUTES:
        raise QueryError(
            f"That start is {minutes // 1440} days back. The longest window "
            f"is {MAX_CUSTOM_MINUTES // 1440} days."
        )

    return Window(
        key=range_key,
        label=f"since {start.strftime('%d %b %H:%M')} UTC",
        minutes=minutes,
        bucket_minutes=_bucket_for(minutes),
        start=start.isoformat(),
    )


def resolve_window(range_key: str) -> Window:
    """The window a range key names — a preset, or a custom start."""
    if range_key.startswith(CUSTOM_PREFIX):
        return _custom_window(range_key)

    preset = RANGES.get(range_key)
    if preset is None:
        raise QueryError(
            f"Unknown range {range_key!r}. Use one of: {', '.join(RANGES)}, "
            f"or '{CUSTOM_PREFIX}<ISO instant>' for a window of your own."
        )

    minutes, bucket = preset
    return Window(
        key=range_key,
        label=RANGE_LABELS.get(range_key, range_key),
        minutes=minutes,
        bucket_minutes=bucket,
    )

# How much gauge the held reference is seeded from, in minutes. Wide enough
# that several samples go into it at the short ranges, where a bucket holds one
# reading and carries the instrument's dither undiminished. Buckets at or above
# this already average that many minutes internally and need a single one.
SEED_MINUTES = 5

MEAN = "mean"
DELTA = "delta"
DRAWDOWN = "drawdown"
FILLUP = "fillup"
MODES = (MEAN, DELTA, DRAWDOWN, FILLUP)


def resolve_range(range_key: str) -> tuple[int, int]:
    """(window minutes, bucket minutes) for a range key."""
    window = resolve_window(range_key)
    return window.minutes, window.bucket_minutes


def seed_buckets(bucket_minutes: int) -> int:
    """How many lead-in buckets the reference is seeded from.

    A fixed span of gauge rather than a fixed count: at 1-minute buckets that
    is five readings to take a median of, and at 30-minute buckets it is the
    one bucket that already averaged thirty.
    """
    return max(1, -(-SEED_MINUTES // bucket_minutes))


def series(
    measurement: str,
    field: str,
    range_key: str,
    group_by: str | None = None,
    tags: dict[str, str] | None = None,
    mode: str = MEAN,
    deadband: float = 0.0,
    cumulative: bool = False,
) -> dict[str, Any]:
    """Bucketed points per series, ready to plot.

    `deadband` is the smallest movement the instrument can be trusted to have
    actually seen, in the field's own units. Below it, a change mode reports
    no change. Zero — the default — trusts every reading exactly as it comes.

    `cumulative` runs a total across the window instead of reporting each
    bucket on its own. It answers "how much altogether since the window
    opened", which is a different question from "how much just then" and the
    one a total is usually wanted for.

    Returns the query it ran alongside the data, so a chart is as checkable as
    a chat answer.
    """
    if mode not in MODES:
        raise QueryError(f"Unknown mode {mode!r}. Use one of: {', '.join(MODES)}.")

    if cumulative and mode == MEAN:
        # Adding up temperatures produces a number with no referent. Only a
        # per-bucket quantity has a running total.
        raise QueryError("Cumulative needs a change mode, not 'mean'.")

    if deadband < 0:
        raise QueryError(f"Deadband must not be negative, got {deadband!r}.")

    window = resolve_window(range_key)
    bucket = window.bucket_minutes

    # Lead-in for the change modes: the first bucket the reader asked for is
    # drawn from the difference against what came before it, so that has to be
    # fetched even though it is never plotted. Several buckets of it, not one —
    # see THE SEED above for what one costs.
    seeds = seed_buckets(bucket)
    lead = 0 if mode == MEAN else bucket * seeds

    filters = tuple(
        TagFilter(key, (str(value),)) for key, value in (tags or {}).items()
    )

    if window.start is not None:
        # Pinned to the instant the reader picked, not to now() minus the
        # distance to it. The two are the same at the moment the request is
        # built and drift apart immediately after, which would mean a chart
        # captioned "since 14:00" quietly starting a few seconds later on
        # every refetch — and the twelve panels of one page beginning at
        # twelve slightly different places.
        opens = ql.shift(window.start, -lead) if lead else window.start
        win = TimeWindow("absolute", start=opens)
    else:
        win = TimeWindow("relative", minutes=window.minutes + lead)

    # mean() for every mode, so that a level and the consumption derived from
    # it are the same number read two ways rather than two different samples.
    structured = Query(
        measurement=measurement,
        selects=(Select(field, "mean"),),
        filters=filters,
        window=win,
        group_by=GroupBy(
            bucket_minutes=bucket,
            tags=((group_by,) if group_by else ()),
            fill_none=True,
        ),
    )

    result = get_data_source().run(structured)
    query = result["query"]
    unit, unit_source = unit_for(measurement, field)

    collected = [
        entry
        for entry in (
            _read_series(
                series_tags, columns, values, mode, deadband, cumulative, seeds
            )
            for series_tags, columns, values in ql.rows(result)
        )
        if entry["points"]
    ]

    return {
        "query": query,
        "measurement": measurement,
        "field": field,
        "mode": mode,
        "unit": unit,
        "unit_source": unit_source,
        "range": window.key,
        "range_label": window.label,
        "window_minutes": window.minutes,
        "bucket_minutes": bucket,
        "series": collected,
    }


def _read_series(
    series_tags: dict[str, str],
    columns: list[str],
    values: list[list[Any]],
    mode: str,
    deadband: float = 0.0,
    cumulative: bool = False,
    seeds: int = 1,
) -> dict[str, Any]:
    """One InfluxDB series turned into plottable points.

    `seeds` is how many leading readings establish the reference the change
    modes measure against. They are consumed rather than plotted, having
    nothing before them to be a change from.
    """
    if mode == MEAN:
        points = [
            {"t": record["time"], "v": round(float(record["mean"]), 4)}
            for record in ql.records(columns, values)
            if record.get("time") is not None and record.get("mean") is not None
        ]
        return {"tags": series_tags, "points": points}

    # An empty bucket is not a reading of zero, and it is not a reading of the
    # last known value either. The next bucket that does report is a change
    # from the last one that did, so the gaps simply leave the sequence.
    readings = [
        (record["time"], float(record["mean"]))
        for record in ql.records(columns, values)
        if record.get("time") is not None and record.get("mean") is not None
    ]

    # Only where an instrument has declared a noise floor. A zero deadband is
    # the caller saying every reading is to be trusted exactly as it comes.
    if deadband:
        readings = _reject_spikes(readings, deadband)

    if len(readings) < 2:
        # Nothing to be a change from.
        return {"tags": series_tags, "points": []}

    # Never more than half the series, so a gappy lead-in eats into the window
    # rather than swallowing it: the query fetches `seeds` buckets of lead-in,
    # but an instrument that went quiet across them leaves fewer readings there
    # than buckets asked for, and the shortfall would come out of the plot.
    taken = max(1, min(seeds, len(readings) // 2))

    # The level the next change is measured against. It holds still while the
    # readings only wobble, and moves the moment one of them means something.
    reference = _seed_reference([level for _, level in readings[:taken]], deadband)

    # The newest reading has no successor, so `_reject_spikes` cannot judge it:
    # a glitch and a real draw look identical until the next bucket says which
    # it was. Charging it means a live dashboard bills every edge glitch in
    # full — on 2026-08-21 the 19:51 bucket read 1949.2 L between neighbours of
    # 1967.0 and 1962.8 and was charged as 17.4 L of use, against 4.2 L that
    # had really gone. So it is held back until confirmed. Nothing is lost: the
    # reference does not move, so whatever really went is charged whole to the
    # bucket that confirms it, one bucket later.
    pending = -1 if deadband else None

    points = []
    for moment, level in readings[taken:pending]:
        if abs(level - reference) < deadband:
            # Inside the noise floor. Report nothing, and leave the reference
            # where it is — a real drift too slow to clear the threshold in
            # one bucket goes on accumulating against it until it does.
            points.append({"t": moment, "v": 0.0})
            continue

        points.append({"t": moment, "v": _change(reference, level, mode)})
        reference = level

    if cumulative:
        _accumulate(points)

    return {"tags": series_tags, "points": points}


def _median(levels: list[float]) -> float:
    ordered = sorted(levels)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _seed_reference(levels: list[float], deadband: float) -> float:
    """The level the first reported change is measured against.

    Where the tank was STILL across the lead-in, the median of those readings
    is the level and everything around it is dither. A median rather than a
    mean because the first reading of a series is the one excursion
    `_reject_spikes` cannot correct — it has no left-hand neighbour to be
    judged against — and a mean would carry a share of it into every bar in
    the window.

    Where the tank was already MOVING when the window opened, a median sits
    behind the level by half the lead-in and charges that lag to the first bar
    as use. The last reading is taken instead: mid-movement, the most recent
    reading is the honest anchor.

    Stillness is judged by TREND, not by spread. Spread is the intuitive test
    and it does not work: dither is bounded per reading but its peak-to-peak
    grows with how many readings you look at, so a wide enough lead-in on a
    perfectly still tank exceeds any fixed threshold and reports motion. The
    two halves of the lead-in are compared by median instead — a quantity
    dither moves barely at all and a real drain moves by most of its drop.

    A zero deadband is the caller trusting every reading exactly as it comes,
    which leaves no basis for calling anything dither; the comparison is then
    against zero, always reads as moving, and the last reading is used. That is
    what every non-tank panel gets, and it is what this function did before
    there was a seed wider than one.
    """
    half = len(levels) // 2
    if half and abs(_median(levels[-half:]) - _median(levels[:half])) >= deadband:
        return levels[-1]
    return _median(levels)


def _accumulate(points: list[dict[str, Any]]) -> None:
    """Turn per-bucket amounts into a running total, in place.

    A quiet bucket contributes nothing and the total holds level, which is the
    reading a flat stretch should give. Rounded at each step rather than at the
    end, so the last point equals the sum of the bars a reader can see.
    """
    total = 0.0
    for point in points:
        total = round(total + point["v"], 4)
        point["v"] = total


def _reject_spikes(
    readings: list[tuple[str, float]], deadband: float
) -> list[tuple[str, float]]:
    """Replace one-bucket excursions with the level either side of them.

    A bucket sitting beyond BOTH its neighbours, in the same direction and by
    more than the instrument can be trusted for, is not a movement the tank
    made — water does not leave and come back within a bucket. Left in, the
    one-sided modes bill it twice: the departure is charged as use and the
    return is written off as a refill, or the other way round.

    Each such bucket takes the median of itself and its two neighbours, which
    is whichever neighbour is nearer. That removes an excursion and leaves a
    step or a ramp alone: where the level departs and STAYS departed, the
    second bucket confirms the first and neither is beyond the other. Two
    buckets of agreement is the same standard the deadband already holds a
    slow drain to, applied to a fast one.

    Neighbours are read from the original series, so a corrected bucket never
    becomes the evidence for correcting the next. Every bucket that is not an
    excursion keeps its own reading exactly, which is what lets a consumption
    chart still be the level chart differenced rather than a second opinion
    about it.

    The limit, stated plainly: a real draw that is refilled within one bucket
    looks exactly like a glitch on this evidence, and is read as one.
    """
    if len(readings) < 3:
        return readings

    kept = list(readings)
    for index in range(1, len(readings) - 1):
        (_, before), (moment, level), (_, after) = readings[index - 1 : index + 2]

        above_both = level - before > deadband and level - after > deadband
        below_both = before - level > deadband and after - level > deadband
        if above_both or below_both:
            kept[index] = (moment, sorted((before, level, after))[1])

    return kept


def _change(previous: float, current: float, mode: str) -> float:
    """What one bucket contributes, given the level it is measured against.

    The two one-sided modes are mirror images, and which one answers a
    question depends on what the tank is for. On a SUPPLY tank a fall is
    consumption and a rise is a delivery, so `drawdown` is the useful half. On
    a WASTE tank it is the other way round — a rise is what the habitat
    produced and a fall is a service emptying — so `fillup` is. Neither is
    "the" consumption; the tank's role decides.
    """
    change = current - previous
    if mode == DELTA:
        return round(change, 4)

    if mode == FILLUP:
        # Only a rise counts. A fall is the tank being emptied, not negative
        # production, so it contributes nothing rather than cancelling real
        # inflow earlier in the window.
        return round(max(0.0, change), 4)

    # DRAWDOWN: only a fall counts as use. A rise is a refill, not negative
    # consumption, so it contributes nothing rather than cancelling real use.
    return round(max(0.0, -change), 4)
