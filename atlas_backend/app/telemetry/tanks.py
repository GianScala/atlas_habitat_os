"""Flow through a tank, from a level gauge.

The third kind of number in this habitat, and the one that had no tool.

  A RATE or LEVEL at an instant — temperature, power draw, CO2. Averaging it
  is meaningful; differencing it is not. `summarize()` handles these.

  A CUMULATIVE TOTALISER that only climbs — the energy meter. Differencing it
  is meaningful; averaging it is not. `get_consumption()` handles these.

  A STOCK, whose LEVEL is a state and whose MOVEMENT is a flow. A water tank.
  Neither of the above works: the mean of a tank level says only where it
  tended to sit, and last-minus-first says only where it happened to end up
  relative to where it started. Both discard the thing being asked about.

The distinction that matters is that a stock moves in two directions for two
unrelated physical reasons, and netting them destroys both. Over the three
days to 2026-08-21 the clean water tank rose 801 L on a single delivery and
fell 431 L into the habitat. Its net change was +367 L — a number that is
correct, is not consumption, is not refill, and is not the answer to any
question anyone asks. Reporting it as "the change" is how a real answer came
to say the tank had gone UP while the crew was drinking from it.

So this module never nets. It reports how much the level fell and how much it
rose, separately, and leaves the naming of those two quantities to whoever
knows what the tank is for: on a supply tank the fall is consumption and the
rise is a delivery, on a waste tank the rise is what was produced and the fall
is a service emptying. Same physics, opposite vocabulary.

Two hazards are handled here rather than left to the caller:

  NOISE. Differencing amplifies it and one-sided accounting rectifies it, so a
  motionless tank reports steady use forever. Beaten by averaging into
  analysis buckets and then by a deadband held against a reference level —
  see `instruments.py` for the measured floors and `timeseries.py` for why the
  reference is held rather than stepped.

  CLIPPING. Each analysis bucket is a mean, so buckets coarser than the events
  in them pull the peaks inward and shorten every movement measured across
  them. See `influxql.resolution_minutes` for what that costs.

The reconciliation is always returned: fell, rose, the net implied by them,
the net implied by the opening and closing levels, and the gap between the
two. That gap is the deadband's tail, it is bounded, and publishing it is what
makes the figure checkable rather than merely plausible.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.errors import QueryError
from app.datasource import get_data_source
from app.datasource.query import GroupBy, Query, Select, TimeWindow
from app.telemetry import influxql as ql
from app.telemetry import instruments
from app.telemetry.filters import envelope, prepare_query

# Below this fraction of the requested window actually carrying readings, a
# per-day average is quoted against a window the data does not cover.
COVERAGE_FLOOR = 0.9

# Reporting periods. Deliberately the same names summarize() and
# get_consumption() use, so `group_by` means one thing across every tool.
PERIODS = ("hour", "day", "week")


def get_tank_flow(
    measurement: str,
    field: str | None = None,
    location: str | None = None,
    tags: dict | None = None,
    days: float | None = None,
    group_by: str = "day",
    start: str | None = None,
    end: str | None = None,
    deadband: float | None = None,
    offset_minutes: int = 0,
) -> dict:
    """How much a level fell and how much it rose, per period and in total.

    Every series (every tank) is decomposed on its own and reported on its
    own. Unlike `get_consumption`, nothing is summed across series: two tanks
    holding different things have no meaningful total, and a clean tank added
    to a grey one is not a quantity.

    `offset_minutes` moves the reporting periods off UTC midnight to the local
    one — how far the habitat's clock is ahead of UTC. It decides only which
    period a movement is filed under; the totals are the same either way.
    """
    if group_by not in PERIODS:
        raise QueryError(f"group_by must be one of {list(PERIODS)}, got {group_by!r}")

    field, filters, applied, matched, unit, unit_source = prepare_query(
        measurement, field, location, tags
    )
    try:
        deadband, deadband_source = instruments.resolve_deadband(
            measurement, field, deadband
        )
    except ValueError as exc:
        raise QueryError(str(exc)) from exc

    span_days = ql.window_span_days(days, start, end)
    resolution = ql.resolution_minutes(None if span_days is None else span_days * 1440)
    _, window_label = ql.window(days, start, end, lead_minutes=resolution)

    # The window, widened at its start by a lead-in bucket so the first reported
    # movement has something to measure against (see influxql.window's lead).
    if start or end:
        opens = ql.shift(start, -resolution) if start else None
        win = TimeWindow("absolute", start=opens, end=end)
    elif days is None:
        win = TimeWindow("all")
    else:
        win = TimeWindow("relative", minutes=max(1, int(float(days) * 1440)) + resolution)

    structured = Query(
        measurement=measurement,
        selects=(Select(field, "mean"),),
        filters=tuple(filters),
        window=win,
        group_by=GroupBy(all_tags=True, bucket_minutes=resolution, fill_none=True),
    )

    result = get_data_source().run(structured)
    query = result["query"]

    out = envelope(measurement, field, applied, matched, unit, unit_source, query)
    out.update(
        {
            "days": days,
            "window": window_label,
            "group_by": group_by,
            "resolution_minutes": resolution,
            "deadband": deadband,
            "deadband_source": deadband_source,
            "period_offset_minutes": offset_minutes,
        }
    )

    if deadband_source == "unknown":
        out["deadband_warning"] = (
            f"No measured noise floor for {measurement}.{field}, so every "
            "reading was trusted exactly as it came and no deadband was "
            "applied. On a noisy gauge that inflates BOTH figures, because "
            "each wobble is counted once as a fall and once as a rise. Treat "
            "these as upper bounds and say so."
        )

    series = [
        entry
        for entry in (
            _decompose(series_tags, columns, values, deadband, group_by, offset_minutes)
            for series_tags, columns, values in ql.rows(result)
        )
        if entry is not None
    ]
    if not series:
        return out

    basis = _basis_days(series, span_days)
    for entry in series:
        _attach_rates(entry, basis["days"])
        _attach_summary(entry, unit, unit_source, basis["days"])

    out["series_count"] = len(series)
    out["data"] = {"series": series, "basis_days": basis["days"]}
    out["basis"] = basis["explanation"]
    out["reading"] = _reading_note(measurement, applied)

    if basis.get("coverage_warning"):
        out["coverage_warning"] = basis["coverage_warning"]

    if declared := _declared_stock(measurement, applied):
        out["stock"] = declared

    if len(series) > 1:
        distinguishing = sorted(
            {key for entry in series for key in entry["tags"]} - set(applied)
        )
        out["series_note"] = (
            f"{len(series)} separate series, distinguished by {distinguishing}. "
            "Each was decomposed on its own and NONE were summed — different "
            "tanks hold different things. Report them separately, or filter on "
            "those tags to narrow to one."
        )
    return out


def _declared_stock(measurement: str, applied: dict) -> dict | None:
    """What the habitat says this tank IS, if the query narrowed to one.

    A gauge cannot know whether it watches a supply or a waste tank, so the
    habitat profile declares it. When the filters match a declared stock, the
    result carries its label and role and the reading note below stops hedging.
    """
    from app.habitat import profile

    stock = profile().stock_role(measurement, applied)
    if not stock:
        return None
    return {
        "key": stock.get("key"),
        "label": stock.get("label"),
        "role": stock.get("role"),
        "noun": stock.get("noun"),
    }


def _reading_note(measurement: str, applied: dict) -> str:
    """How to read `fell` and `rose` on THIS tank.

    Generic by default — the movements are named quantities only once someone
    says what the tank is for. Where the habitat has declared the role, this
    says which figure is consumption instead of leaving it to the reader.
    """
    common = (
        " Never report the net as consumption — it is a delivery minus a "
        "drawdown and describes neither. Each series carries a `summary` line "
        "with both figures already stated; quote it rather than reassembling "
        "the numbers, and check any figure you write against it."
    )

    stock = _declared_stock(measurement, applied)
    role = (stock or {}).get("role", "")
    label = (stock or {}).get("label") or measurement

    if role == "supply":
        return (
            f"This habitat declares {label} a SUPPLY stock: `fell` is what was "
            "CONSUMED and `rose` is a delivery or refill. Report `fell` as the "
            "consumption figure and say so." + common
        )
    if role == "waste":
        return (
            f"This habitat declares {label} a WASTE stock: `rose` is what the "
            "habitat PRODUCED and `fell` is the tank being emptied. Report "
            "`rose` as the production figure and say so." + common
        )
    return (
        "`fell` and `rose` are physical movements of the level, not named "
        "quantities. On a supply tank the fall is consumption and the rise is "
        "a delivery; on a waste tank the rise is what was produced and the "
        "fall is a service emptying. This habitat has not declared which this "
        "tank is, so say which convention you applied." + common
    )


# --------------------------------------------------------------------------
# Decomposition
# --------------------------------------------------------------------------


def _decompose(
    series_tags: dict,
    columns: list,
    values: list,
    deadband: float,
    group_by: str,
    offset_minutes: int = 0,
) -> dict[str, Any] | None:
    """One series' level history turned into falls and rises per period.

    The first bucket is the lead-in: it is the level everything after is
    measured against and is never itself attributed to a period, because there
    is nothing before it to be a change from. That is why the query reaches
    one resolution bucket further back than the window asks for.
    """
    levels = sorted(
        (record["time"], float(record["mean"]))
        for record in ql.records(columns, values)
        if record.get("time") is not None and record.get("mean") is not None
    )
    if len(levels) < 2:
        return None

    opening_time, opening_level = levels[0]
    reference = opening_level
    periods: dict[str, dict] = {}
    moves = 0

    for moment, level in levels[1:]:
        key = _period_start(moment, group_by, offset_minutes)
        # Registered whether or not anything moved, so a quiet day appears as
        # a row of zeroes rather than vanishing from the breakdown.
        period = periods.setdefault(
            key, {"period_start": key, "fell": 0.0, "rose": 0.0}
        )
        if abs(level - reference) < deadband:
            # Inside the noise floor. Report nothing and leave the reference
            # where it is, so a real drift too slow to clear the threshold in
            # one bucket goes on accumulating against it until it does.
            continue

        change = level - reference
        if change < 0:
            period["fell"] = round(period["fell"] - change, 4)
        else:
            period["rose"] = round(period["rose"] + change, 4)
        moves += 1
        reference = level

    closing_time, closing_level = levels[-1]
    ordered = [periods[key] for key in sorted(periods)]
    for period in ordered:
        period["net"] = round(period["rose"] - period["fell"], 4)

    kept, truncated = ql.trim_periods(ordered)
    total_fell = round(sum(p["fell"] for p in ordered), 4)
    total_rose = round(sum(p["rose"] for p in ordered), 4)
    net_from_levels = round(closing_level - opening_level, 4)

    entry: dict[str, Any] = {
        "tags": series_tags,
        "per_period": kept,
        "opening_level": opening_level,
        "opening_time": opening_time,
        "closing_level": closing_level,
        "closing_time": closing_time,
        "total_fell": total_fell,
        "total_rose": total_rose,
        "net_from_moves": round(total_rose - total_fell, 4),
        "net_from_levels": net_from_levels,
        "unreconciled": round(net_from_levels - (total_rose - total_fell), 4),
        "moves_counted": moves,
        "analysis_buckets": len(levels),
    }
    if truncated:
        entry["periods_total"] = len(ordered)
        entry["truncated"] = f"most recent {ql.MAX_PERIODS} periods shown"
    return entry


def _period_start(moment: str, group_by: str, offset_minutes: int = 0) -> str:
    """The reporting period an analysis bucket belongs to, as UTC ISO.

    Truncation happens in the habitat's own frame — the moment is carried
    `offset_minutes` forward into local time, cut to the hour, day, or week
    there, and carried back. The answer is still a UTC instant; it is just the
    instant local midnight fell on rather than the one UTC's did.
    """
    parsed = datetime.fromisoformat(str(moment).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    local = parsed.astimezone(UTC) + timedelta(minutes=offset_minutes)

    if group_by == "hour":
        start = local.replace(minute=0, second=0, microsecond=0)
    elif group_by == "week":
        midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
        start = midnight - timedelta(days=midnight.weekday())
    else:
        start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return (start - timedelta(minutes=offset_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------
# Rates
# --------------------------------------------------------------------------


def _basis_days(series: list[dict], span_days: float | None) -> dict:
    """How many days a per-day average should divide by, and why.

    The requested window when there is one — NOT the number of calendar
    periods it touches. A rolling three-day window that starts mid-morning
    touches four UTC days, and dividing by four understates every daily figure
    by a quarter while looking entirely reasonable.
    """
    observed = max(
        (_hours_between(e["opening_time"], e["closing_time"]) for e in series),
        default=0.0,
    ) / 24

    if span_days is None:
        return {
            "days": round(observed, 4) or 1.0,
            "explanation": (
                f"No window was requested, so per-day figures divide by the "
                f"{observed:.2f} days the readings actually span."
            ),
        }

    result = {
        "days": round(span_days, 4),
        "explanation": (
            f"Per-day figures divide by the {span_days:g} days requested, not "
            "by the number of calendar days the window touches."
        ),
    }
    if observed < span_days * COVERAGE_FLOOR:
        result["coverage_warning"] = (
            f"Readings span only {observed:.2f} of the {span_days:g} days "
            "requested. The per-day figures divide by the requested window, so "
            "they understate the rate during the hours actually covered. Say "
            "that the record is incomplete."
        )
    return result


def _hours_between(start: str, end: str) -> float:
    first = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
    last = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
    return max(0.0, (last - first).total_seconds() / 3600)


def _attach_rates(entry: dict, basis_days: float) -> None:
    """Per-day figures for one series."""
    if basis_days <= 0:
        return
    entry["fell_per_day"] = round(entry["total_fell"] / basis_days, 4)
    entry["rose_per_day"] = round(entry["total_rose"] / basis_days, 4)


def _attach_summary(
    entry: dict, unit: str, unit_source: str, basis_days: float
) -> None:
    """One sentence stating both directions, ready to be quoted.

    Four numbers with near-identical names sit next to each other in this
    result, and two of them are the same quantity at different scales. That is
    an easy thing to transpose while writing an answer, and a transposed
    figure reads exactly as confidently as a correct one — a reader has no way
    to catch it. Assembling the sentence here, once, from the values that were
    actually computed removes the step where it can go wrong.
    """
    suffix = f" {unit}" if unit_source == "known" and unit else ""
    name = " ".join(str(v) for v in entry["tags"].values()) or "this series"
    per_day = ""
    if "fell_per_day" in entry:
        per_day = (
            f" That is {entry['fell_per_day']:g}{suffix} per day down and "
            f"{entry['rose_per_day']:g}{suffix} per day up over "
            f"{basis_days:g} day(s)."
        )

    entry["summary"] = (
        f"{name}: the level FELL by {entry['total_fell']:g}{suffix} and ROSE "
        f"by {entry['total_rose']:g}{suffix}, opening at "
        f"{entry['opening_level']:g}{suffix} and closing at "
        f"{entry['closing_level']:g}{suffix}.{per_day} Quote these two "
        "figures as they stand — do not swap them, and do not report one of "
        "them twice."
    )
