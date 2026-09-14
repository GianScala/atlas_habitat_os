"""The dashboard's panel catalogue.

Which measurement, which field, which rooms, and how to aggregate — all decided
outside the browser. The frontend asks for a range and gets back panels it can
draw without knowing anything about the habitat.

NOTHING HERE IS HABITAT-SPECIFIC. A panel catalogue comes from one of two
places, in order:

  1. the habitat profile's `dashboard_panels:` — a curated set the mission
     chose, which is how a deployment gets exactly the charts it wants;
  2. failing that, `derive_panels()` below, which builds a reasonable catalogue
     from whatever the database actually turns out to hold.

Either way the result is filtered against the live schema, so a panel for a
sensor this deployment does not have is hidden rather than drawn empty.

A note on the difference from the chat side: the assistant must never assume
what exists, because a wrong "there is no sensor for that" is a claim someone
might act on. A dashboard is the opposite — a curated view someone chose. So
naming rooms and excluding rollups is appropriate here in a way it would not
be in `telemetry/`; it just has to be the HABITAT's naming, not one habitat's
baked into the source.
"""

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from functools import partial
from typing import Any

from app.core.concurrency import gather
from app.core.errors import AtlasError
from app.core.logging import get_logger
from app.habitat import profile
from app.telemetry import discovery, instruments
from app.telemetry import timeseries as ts

log = get_logger(__name__)


def _not_a_room() -> frozenset[str]:
    """Location tag values this habitat says are not rooms.

    Crew, vehicles, external weather, experiment rigs — anything a per-room
    chart should leave out. Declared in the habitat profile, because which tag
    values name an interior space is a fact about the habitat.
    """
    return frozenset(profile().non_room_locations)


def _rollup_values() -> frozenset[str]:
    """Tag values that total other meters, so a per-room chart excludes them.

    Charting a whole-habitat rollup beside the rooms it is made of would draw
    the same watts twice. Shared with the consumption arithmetic, which excludes
    the same values from its sums — a chart and an answer must agree.
    """
    from app.telemetry.aggregation import _aggregate_tag_values

    return frozenset(_aggregate_tag_values())


@dataclass(frozen=True)
class Panel:
    """One chart."""

    id: str
    title: str
    subtitle: str
    measurement: str
    field: str
    chart: str = "line"  # line | area | bar
    mode: str = ts.MEAN
    group_by: str | None = None
    tags: dict[str, str] = dataclass_field(default_factory=dict)
    exclude: frozenset[str] = frozenset()
    # Shown when the database records no unit for the field.
    unit_note: str | None = None
    group: str = "Environment"
    # Smallest movement this instrument can be trusted to have really seen,
    # in the field's own units. Only the change modes use it. See the deadband
    # note in `telemetry/timeseries.py` for why it is needed and how it works.
    deadband: float = 0.0
    # Plot the running total across the window rather than each bucket alone.
    # Only meaningful for the change modes.
    cumulative: bool = False


def derive_panels() -> tuple[Panel, ...]:
    """A catalogue built from what the database actually holds.

    The zero-configuration path: a habitat that declares no `dashboard_panels:`
    still gets a useful dashboard. Every measurement carrying a location-like
    tag becomes a per-room chart; the habitat's declared stocks become level and
    flow charts; and a declared cumulative mission meter becomes a consumption
    chart. Nothing is invented — a measurement absent from the database yields
    no panel, and the result is availability-filtered like any catalogue.

    A mission that wants different charts declares `dashboard_panels:` and this
    is not consulted.
    """
    from app.telemetry import discovery

    prof = profile()
    panels: list[Panel] = []

    try:
        measurements = discovery.discover()["habitat"]
    except AtlasError as exc:
        log.warning("Cannot derive a dashboard: %s", exc.message)
        return ()

    stock_measurements = set(prof.stock_measurements)
    excluded = frozenset(_not_a_room() | _rollup_values())

    # --- per-room conditions: anything tagged by place ---------------------
    for measurement in measurements:
        if measurement in stock_measurements:
            continue  # a tank is a stock, not a room reading
        try:
            location_key = discovery.default_location_key(measurement)
            fields = [f["field"] for f in discovery.field_keys(measurement)]
        except AtlasError:
            continue
        if not location_key or not fields:
            continue
        field = "value" if "value" in fields else fields[0]
        panels.append(
            Panel(
                id=f"room_{measurement.lower()}",
                title=f"{measurement} by room",
                subtitle=f"{measurement} per location, averaged across its sensors",
                measurement=measurement,
                field=field,
                group_by=location_key,
                exclude=excluded,
                group="Environment",
            )
        )

    # --- stocks: a level, and the movement that matters on it --------------
    for stock in prof.stocks:
        measurement = str(stock.get("measurement", ""))
        field = str(stock.get("field", ""))
        if not measurement or not field:
            continue
        key = str(stock.get("key", measurement)).lower()
        label = str(stock.get("label", measurement))
        tags = dict(stock.get("tags") or {})
        role = str(stock.get("role", "")).lower()
        deadband, _ = instruments.deadband_for(measurement, field)

        panels.append(
            Panel(
                id=f"stock_{key}_level",
                title=f"{label} level",
                subtitle=f"Contents of {label.lower()}",
                measurement=measurement,
                field=field,
                tags=tags,
                chart="area",
                group="Stocks",
            )
        )
        # On a SUPPLY stock the fall is consumption; on a WASTE stock the rise
        # is what the habitat produced. Anything else gets the signed net.
        if role == "supply":
            mode, title, subtitle = (
                ts.DRAWDOWN,
                f"{label} consumed",
                "How far the level fell in each interval. A refill counts as "
                "zero use, not negative use.",
            )
        elif role == "waste":
            mode, title, subtitle = (
                ts.FILLUP,
                f"{label} produced",
                "How far the level rose in each interval. An emptying counts "
                "as zero production.",
            )
        else:
            mode, title, subtitle = (
                ts.DELTA,
                f"{label} change",
                "Net change in each interval. Positive is arriving, negative "
                "is leaving.",
            )
        panels.append(
            Panel(
                id=f"stock_{key}_flow",
                title=title,
                subtitle=subtitle,
                measurement=measurement,
                field=field,
                tags=tags,
                mode=mode,
                chart="bar",
                deadband=deadband,
                group="Stocks",
            )
        )

    # --- whole-habitat consumption from a cumulative mission meter ---------
    for resource in prof.mission_resources:
        if str(resource.get("kind", "")) != "cumulative":
            continue
        measurement = str(resource.get("measurement", ""))
        field = str(resource.get("field", ""))
        if not measurement or not field:
            continue
        label = str(resource.get("label", measurement))
        panels.append(
            Panel(
                id=f"consumption_{str(resource.get('key', measurement)).lower()}",
                title=f"{label} consumed",
                subtitle=(
                    "Totaliser differenced per interval: what was used in each "
                    "bucket, not the meter's running total."
                ),
                measurement=measurement,
                field=field,
                tags=dict(resource.get("tags") or {}),
                mode=ts.DELTA,
                chart="bar",
                group="Consumption",
            )
        )

    return tuple(panels)




def _panel_from_config(raw: dict) -> Panel:
    """One Panel from a habitat profile's `dashboard_panels:` entry.

    Every field maps straight to the Panel dataclass; only `exclude` (a list in
    YAML) and `deadband` (which may be "auto" to read the profile's noise floor)
    need translating.
    """
    deadband = raw.get("deadband", 0.0)
    measurement = str(raw["measurement"])
    field = str(raw["field"])
    if deadband == "auto":
        deadband, _ = instruments.deadband_for(measurement, field)

    # A panel grouped by place also leaves out whatever the habitat says is not
    # a room, so every per-room chart does not have to repeat that list.
    exclude = frozenset(raw.get("exclude") or ())
    if raw.get("group_by"):
        exclude |= _not_a_room()

    return Panel(
        id=str(raw["id"]),
        title=str(raw.get("title", raw["id"])),
        subtitle=str(raw.get("subtitle", "")),
        measurement=measurement,
        field=field,
        chart=str(raw.get("chart", "line")),
        mode=str(raw.get("mode", ts.MEAN)),
        group_by=raw.get("group_by"),
        tags=dict(raw.get("tags") or {}),
        exclude=exclude,
        unit_note=raw.get("unit_note"),
        group=str(raw.get("group", "Environment")),
        deadband=float(deadband),
        cumulative=bool(raw.get("cumulative", False)),
    )


def catalogue() -> tuple[Panel, ...]:
    """The panels for this habitat.

    A habitat that declares `dashboard_panels:` in its profile gets exactly
    those; one that declares none gets a catalogue derived from its database.
    Either way the panels are then filtered against what the database actually
    holds, so a catalogue can never draw a chart for a sensor this deployment
    does not have.
    """
    declared = profile().dashboard_panels
    if declared:
        return tuple(_panel_from_config(p) for p in declared)
    return derive_panels()


def _available(panels: tuple[Panel, ...]) -> list[Panel]:
    """Drop panels whose measurement or field is not in the connected database.

    This is what makes the dashboard adapt to the habitat: a panel for a sensor
    that isn't there is hidden, not drawn empty. If the database can't be reached
    at all, nothing is filtered — the panels then report the real failure rather
    than the page silently going blank.
    """
    try:
        measurements = set(discovery.discover()["habitat"])
    except AtlasError as exc:
        log.warning("Skipping availability filter — cannot read schema: %s", exc.message)
        return list(panels)

    kept: list[Panel] = []
    for panel in panels:
        if panel.measurement not in measurements:
            continue
        try:
            fields = {f["field"] for f in discovery.field_keys(panel.measurement)}
        except AtlasError:
            fields = set()
        if panel.field not in fields:
            continue
        kept.append(panel)
    return kept


# Tag keys whose raw values mean nothing on their own. Grouping Electricity
# by Phase yields series called "1", "2", "3"; a legend needs "Phase 1".
def _label_for(tags: dict[str, str], group_by: str | None) -> tuple[str, str]:
    """(display label, raw tag value) for one series.

    Tag keys whose raw values mean nothing alone — a phase tag yields "1", "2",
    "3" — carry a prefix from the habitat profile so the legend reads
    "Phase 1". Everything else is looked up in the habitat's zone names.
    """
    if not group_by:
        return "", ""

    raw = tags.get(group_by, "")
    prefix = profile().tag_label_prefixes.get(group_by)
    if prefix:
        return f"{prefix}{raw}", raw

    from app.services import labels

    return labels.display_name(raw, labels.LOCATION) or raw, raw


def _excluded(raw: str, exclude: frozenset[str]) -> bool:
    """Is this tag value one the panel leaves out?

    Case-insensitive, because a habitat's rollup values are matched that way by
    the consumption arithmetic and the two have to agree on which series is a
    total rather than a meter.
    """
    if not raw:
        return False
    lowered = {value.lower() for value in exclude}
    return raw in exclude or raw.lower() in lowered


def _disambiguate(series: list[dict[str, Any]]) -> None:
    """Split two series that landed on the same room name.

    `AirLock` and `Airlock` are separate tag values holding separate data but
    name one place. Merging them would invent an average across two sensor
    groups nobody asked to combine, so both are shown under their raw tags —
    which is the thing that actually tells them apart.
    """
    counts: dict[str, int] = {}
    for entry in series:
        counts[entry["key"]] = counts.get(entry["key"], 0) + 1

    for entry in series:
        if counts.get(entry["key"], 0) <= 1 or not entry["raw"]:
            continue
        entry["key"] = entry["raw"]
        entry["label"] = entry["raw"]


def build_panel(panel: Panel, range_key: str) -> dict[str, Any]:
    """Run one panel's query and shape it for the chart."""
    result = ts.series(
        measurement=panel.measurement,
        field=panel.field,
        range_key=range_key,
        group_by=panel.group_by,
        tags=panel.tags or None,
        mode=panel.mode,
        deadband=panel.deadband,
        cumulative=panel.cumulative,
    )

    series: list[dict[str, Any]] = []
    for entry in result["series"]:
        label, raw = _label_for(entry["tags"], panel.group_by)
        # Case-insensitive: rollup values are matched the same way the
        # consumption arithmetic matches them, so a chart and an answer
        # exclude the same series.
        if panel.group_by and _excluded(raw, panel.exclude):
            continue

        # The key is the ROOM, not the tag that happens to name it here.
        # Temperature calls the dormitory `Container3` and Energy calls it
        # `Dormitory`; keying on the raw tag would make one room look like
        # two and give it a different colour on each chart.
        series.append(
            {
                "key": label or panel.id,
                "label": label or panel.title,
                "raw": raw,
                "points": entry["points"],
            }
        )

    if panel.group_by:
        _disambiguate(series)
        series.sort(key=lambda item: item["label"].lower())

    for entry in series:
        entry.pop("raw", None)

    return {
        "id": panel.id,
        "title": panel.title,
        "subtitle": panel.subtitle,
        "group": panel.group,
        "chart": panel.chart,
        "mode": panel.mode,
        "cumulative": panel.cumulative,
        "unit": result["unit"],
        "unit_source": result["unit_source"],
        "unit_note": panel.unit_note,
        "measurement": panel.measurement,
        "field": panel.field,
        "query": result["query"],
        "bucket_minutes": result["bucket_minutes"],
        "series": series,
        "error": None,
    }


def build_dashboard(range_key: str, panel_ids: list[str] | None = None) -> dict[str, Any]:
    """Every panel for a range.

    One panel failing must not take the page with it — a broken sensor should
    leave a gap, not an error screen. Failures are reported per panel.

    The panels are queried together rather than one after another. They share
    nothing but the window, and one after another meant the reader waited for
    the sum of a dozen round trips to see a window they had already picked.
    """
    window = ts.resolve_window(range_key)  # validate before doing any work

    available = _available(catalogue())
    by_id = {panel.id: panel for panel in available}
    wanted = (
        [by_id[pid] for pid in panel_ids if pid in by_id]
        if panel_ids
        else available
    )

    panels = gather(
        [partial(_build_or_report, panel, range_key) for panel in wanted]
    )

    return {
        "range": window.key,
        "range_label": window.label,
        "panels": panels,
    }


def _build_or_report(panel: Panel, range_key: str) -> dict[str, Any]:
    """One panel, or a panel-shaped account of why it could not be built."""
    try:
        return build_panel(panel, range_key)
    except AtlasError as exc:
        log.warning("Panel %s failed: %s", panel.id, exc.message)
        return _failed_panel(panel, exc.message)


def _failed_panel(panel: Panel, reason: str) -> dict[str, Any]:
    return {
        "id": panel.id,
        "title": panel.title,
        "subtitle": panel.subtitle,
        "group": panel.group,
        "chart": panel.chart,
        "mode": panel.mode,
        "cumulative": panel.cumulative,
        "unit": "",
        "unit_source": "unknown",
        "unit_note": panel.unit_note,
        "measurement": panel.measurement,
        "field": panel.field,
        "query": "",
        "bucket_minutes": 0,
        "series": [],
        "error": reason,
    }
