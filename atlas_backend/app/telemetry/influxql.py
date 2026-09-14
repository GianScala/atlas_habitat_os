"""InfluxQL string construction and parsing helpers.

Pure functions with no knowledge of the database's contents — safe to import
from anywhere in the telemetry package.

Careful: the identifiers and literals passed through here are chosen by a
language model. The approach is to refuse anything surprising rather than to
escape it cleverly.
"""

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.errors import QueryError

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.\- ]+$")

# Bucket sizes offered for per-period breakdowns, in minutes.
BUCKET_MINUTES = {"hour": 60, "day": 1440, "week": 10080}

# Cap on how many periods come back, so an all-history query does not return
# thousands of rows. The most recent are kept.
MAX_PERIODS = 90


def identifier(name: str) -> str:
    """Quote a measurement, field, or tag key for InfluxQL.

    Rejects anything outside a conservative character set rather than trying
    to escape it. The model chooses these names, so refusing surprises is the
    safe move.
    """
    if not isinstance(name, str) or not _SAFE_IDENTIFIER.match(name):
        raise QueryError(f"Unsafe or empty InfluxQL identifier: {name!r}")
    return f'"{name}"'


def literal(value: Any) -> str:
    """Quote a tag value as an InfluxQL string literal."""
    text = str(value)
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def duration(minutes: int) -> str:
    """An InfluxQL duration literal, in whole minutes."""
    return f"{max(1, int(minutes))}m"


def time_group(bucket_minutes: int, offset_minutes: int = 0) -> str:
    """A `GROUP BY time(...)` clause, optionally shifted off UTC midnight.

    InfluxQL buckets from the epoch, and the epoch is a UTC midnight, so a
    daily bucket is a UTC day. That is the wrong day for anyone asking what
    they used "today": a habitat two hours ahead of UTC has already lived two
    hours of its day when the UTC bucket opens, and those two hours are filed
    under yesterday.

    `offset_minutes` is how far the habitat's clock is AHEAD of UTC. The shift
    InfluxQL wants is the opposite sign — its argument moves each boundary
    forward from UTC midnight, and local midnight falls that many minutes
    before it — and is reduced into a single bucket, since shifting by a whole
    bucket lands back where it started.
    """
    span = duration(bucket_minutes)
    shift = int(-offset_minutes) % max(1, int(bucket_minutes))
    if shift == 0:
        return f"time({span})"
    return f"time({span}, {duration(shift)})"


def rows(result: dict) -> list[tuple[dict, list, list]]:
    """Flatten a parsed result into (tags, columns, values) per series."""
    return [(s["tags"], s["columns"], s["values"]) for s in result["series"]]


def records(columns: list, values: list) -> list[dict]:
    """Zip a series' columns and values into dicts."""
    return [dict(zip(columns, row, strict=False)) for row in values]


def timestamp(value: str) -> str:
    """Validate an ISO 8601 instant and return it as a UTC InfluxQL literal.

    Anything that is not a real timestamp is refused rather than escaped — the
    model supplies these strings.
    """
    text = str(value).strip().replace("Z", "+00:00")
    try:
        moment = datetime.fromisoformat(text)
    except ValueError as exc:
        raise QueryError(
            f"Not an ISO 8601 timestamp: {value!r}. Use e.g. "
            f"'2026-08-18T05:00:00Z' (UTC) or '2026-08-18T07:00:00+02:00'."
        ) from exc

    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).strftime("'%Y-%m-%dT%H:%M:%SZ'")


def window(
    days: float | None = None,
    start: str | None = None,
    end: str | None = None,
    lead_minutes: int = 0,
) -> tuple[list[str], str]:
    """(WHERE clauses, human label) for a time window.

    Three ways to say when, in order of precedence:

      start/end   an exact instant — the only correct way to answer "since
                  08:00 on the 18th", because a relative window is measured
                  from now() and drifts as time passes.
      days        a rolling window ending now.
      neither     every point on record.

    `lead_minutes` widens the range QUERIED at its start without changing the
    range the label describes. A change mode needs one bucket of history to
    measure its first bucket against; fetching it is the only honest way to
    get it, since the alternative is inventing a reading that was never taken.
    The label still names the window the caller asked about.
    """
    if start or end:
        clauses: list[str] = []
        parts: list[str] = []
        if start:
            asked = timestamp(start)
            queried = timestamp(shift(start, -lead_minutes)) if lead_minutes else asked
            clauses.append(f"time >= {queried}")
            parts.append(f"from {asked.strip(chr(39))}")
        if end:
            value = timestamp(end)
            clauses.append(f"time <= {value}")
            parts.append(f"to {value.strip(chr(39))}")
        else:
            parts.append("to now")
        return clauses, " ".join(parts)

    if days is None:
        return [], "all available data"

    minutes = max(1, int(float(days) * 1440))
    return (
        [f"time > now() - {duration(minutes + lead_minutes)}"],
        f"rolling last {days} day(s)",
    )


def shift(moment: str, minutes: int) -> str:
    """An ISO instant moved by a signed number of minutes."""
    text = str(moment).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise QueryError(f"Not an ISO 8601 timestamp: {moment!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return (parsed + timedelta(minutes=minutes)).isoformat()


def window_span_days(
    days: float | None = None,
    start: str | None = None,
    end: str | None = None,
) -> float | None:
    """How long the requested window is, in days, or None if open-ended.

    This is what a per-day average must divide by. Dividing by the number of
    calendar buckets the window happens to touch is the classic off-by-one
    here: a rolling three-day window starting mid-morning touches FOUR
    UTC-midnight days, and averaging over four understates the daily figure by
    a quarter while looking entirely reasonable.

    Returns None when the window is all-of-history, where only the data can
    say how long it actually spans.
    """
    if start or end:
        if not start:
            return None
        begin = datetime.fromisoformat(str(start).strip().replace("Z", "+00:00"))
        if begin.tzinfo is None:
            begin = begin.replace(tzinfo=UTC)
        finish = datetime.now(UTC)
        if end:
            finish = datetime.fromisoformat(str(end).strip().replace("Z", "+00:00"))
            if finish.tzinfo is None:
                finish = finish.replace(tzinfo=UTC)
        span = (finish - begin).total_seconds() / 86400
        return round(span, 6) if span > 0 else None

    if days is None:
        return None
    return float(days) if float(days) > 0 else None


def bucket_minutes(group_by: str) -> int:
    """Validate a group_by name and return its size in minutes."""
    minutes = BUCKET_MINUTES.get(group_by)
    if minutes is None:
        raise QueryError(
            f"group_by must be one of {sorted(BUCKET_MINUTES)}, got {group_by!r}"
        )
    return minutes


# Analysis resolutions for differencing a level, finest first. This is a
# different question from how the answer is REPORTED: a month-long question is
# reported per day but is still differenced at a much finer grain, because a
# bucket is averaged BEFORE it is differenced, and averaging clips whatever
# the level did inside the bucket.
RESOLUTION_LADDER = (15, 30, 60, 120, 240, 480, 1440)

# Below this, gauge dither dominates. Measured against the clean water tank
# over three days: 5-minute buckets report 497 L of drawdown where the tank
# demonstrably fell 431 L, a 15% inflation the deadband does not remove.
MIN_RESOLUTION = 15

# How many analysis buckets we are willing to fetch. Generous on purpose:
# these are never returned to the caller, only reduced into reporting periods,
# so the only cost is one larger query.
TARGET_RESOLUTION_BUCKETS = 700


def resolution_minutes(span_minutes: float | None) -> int:
    """Analysis bucket size for differencing a level over a window.

    Errs FINE. The instinct is to smooth a noisy gauge with big buckets, and
    for a level chart that instinct is right, but differencing inverts it:
    each bucket is a mean, so a coarse bucket pulls the peaks and troughs
    inward and every movement measured across it comes out short. The
    shortfall is one-directional and invisible in the answer.

    Measured on three days of the clean water tank, where the level rose from
    930 L to a peak of 1731 L on a single refill and then fell to 1300 L, so
    the true figures are close to 801 L in and 431 L out:

        5-minute buckets    497 L out, 867 L in   noise, inflated 15%
       15-minute buckets    436 L out, 806 L in   within 1% of the truth
       30-minute buckets    422 L out, 792 L in   clipping begins
       60-minute buckets    406 L out, 776 L in   short by 6%
      180-minute buckets    400 L out, 439 L in   refill halved by averaging

    That 439 is the failure worth remembering: at three hours the refill and
    the level before it fall in the same bucket, so half of an 800 L delivery
    simply vanishes into a mean. Noise is handled by the deadband; clipping
    cannot be handled at all once the query has run.
    """
    if span_minutes is None or span_minutes <= 0:
        return MIN_RESOLUTION

    for candidate in RESOLUTION_LADDER:
        if span_minutes / candidate <= TARGET_RESOLUTION_BUCKETS:
            return max(MIN_RESOLUTION, candidate)
    return RESOLUTION_LADDER[-1]


def trim_periods(periods: list[dict]) -> tuple[list[dict], bool]:
    """Keep the most recent MAX_PERIODS. Returns (kept, was_truncated)."""
    if len(periods) <= MAX_PERIODS:
        return periods, False
    return periods[-MAX_PERIODS:], True


def where_clause(clauses: list[str]) -> str:
    """Join clauses into a WHERE body, or a tautology when there are none."""
    return " AND ".join(clauses) if clauses else "1 = 1"
