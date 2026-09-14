"""Load and hold the habitat profile.

One profile per process, read once from YAML. A malformed or missing file is a
warning and an empty profile, never a crash — a habitat with no unit table still
answers questions, it just reports every unit as unrecorded, which is exactly
what ATLAS does for an unlisted field anyway. Failing loudly here would take
the whole assistant down over a preference file.
"""

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from app.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

# Relative HABITAT_CONFIG paths resolve against the backend root, so a profile
# travels with a standalone backend deploy.
_BACKEND_ROOT = Path(__file__).resolve().parents[2]

# Fallbacks used when the profile omits a section. Location tag keys are how a
# generic query finds "where" without knowing a habitat's tag naming; without
# any, per-place queries simply find nothing rather than misbehaving.
_DEFAULT_LOCATION_TAG_KEYS = ("Location", "Connection", "Sensor", "Device", "Host")


@dataclass(frozen=True)
class HabitatProfile:
    """The non-discoverable facts about one habitat."""

    name: str = "habitat"
    location_tag_keys: tuple[str, ...] = _DEFAULT_LOCATION_TAG_KEYS
    internal_prefixes: tuple[str, ...] = ()
    zone_names: dict[str, str] = field(default_factory=dict)
    # measurement -> field -> unit string ("" means dimensionless-but-known).
    units: dict[str, dict[str, str]] = field(default_factory=dict)
    # Fields for which summing across series (e.g. phases) is not meaningful.
    non_summable_fields: tuple[str, ...] = ()
    # Tag values that mark an already-aggregated series (a rollup) rather than a
    # real meter, so consumption sums don't double-count. Matched case-insensitively.
    aggregate_tag_values: tuple[str, ...] = ()
    # measurement -> field -> smallest movement the instrument can be trusted to
    # have seen (a deadband), in the field's own units. Used by tank-flow.
    noise_floors: dict[str, dict[str, float]] = field(default_factory=dict)
    # Optional electrical-phase config for get_latest_all_phases: the keys
    # measurement, phase_tag, phases (list), default_field. Empty if the habitat
    # has no multi-phase electrical meter.
    electrical: dict = field(default_factory=dict)
    # The habitat's STOCKS — tanks and stores whose LEVEL is a state and whose
    # MOVEMENT is a flow. Clean and grey water are the universal example, but a
    # battery charge state or a food store behave identically. Each entry:
    #   key, label, measurement, field, tags, role (supply | waste), noun.
    #
    # `role` is what makes an answer correct rather than merely arithmetic: on a
    # SUPPLY tank the fall is consumption and the rise is a delivery; on a WASTE
    # tank the rise is what the habitat produced and the fall is it being
    # emptied. No sensor knows which it is, so the habitat declares it.
    stocks: tuple[dict, ...] = ()
    # Location tag values that are NOT habitat rooms — crew, vehicles, external
    # weather, experiment rigs. Excluded from per-room charts. Excluding rather
    # than listing rooms means a newly instrumented room appears on its own.
    non_room_locations: tuple[str, ...] = ()
    # Tag keys whose raw values mean nothing alone, and the prefix that fixes
    # them: grouping by a phase tag yields series called "1", "2", "3", and a
    # legend needs "Phase 1". {tag key: prefix}.
    tag_label_prefixes: dict[str, str] = field(default_factory=dict)
    # The resources the mission plan budgets and tracks (water, power, ...), each
    # mapped to the telemetry that measures it. Empty means the mission plan has
    # no resources to track (it still holds the mission frame). Each entry:
    #   key, label, noun, kind (stock | cumulative), measurement, field, tags,
    #   default_daily.
    mission_resources: tuple[dict, ...] = ()
    # The habitat's clock offset from UTC in whole minutes, used as the default
    # day-start until the crew sets one. None falls back to default_plan.json.
    day_start_offset_minutes: int | None = None
    # Dashboard panels for this habitat. Each entry mirrors the Panel dataclass
    # in app/services/dashboard.py. Empty means the dashboard derives a sensible
    # catalogue from whatever the database turns out to hold. Panels are always
    # filtered against the real schema, so a stale entry hides itself rather
    # than drawing an empty chart.
    dashboard_panels: tuple[dict, ...] = ()
    # The dials the crew reads by hand on a round, as {power: [...], water: [...]}.
    # Each entry: key, label, code, group, group_label, stream (warm|cold|none).
    # Empty means this habitat keeps no manual meter log — until the crew adds
    # one in the interface, which stores it in the database instead.
    crew_log_meters: dict = field(default_factory=dict)
    # For the SQL adapter: how this habitat's table maps onto ATLAS's
    # measurement/location/field/time/value model. Empty unless DATA_SOURCE=sql.
    sql_mapping: dict = field(default_factory=dict)

    @property
    def stock_measurements(self) -> tuple[str, ...]:
        """The distinct measurements that hold a stock, for tool gating."""
        seen: list[str] = []
        for stock in self.stocks:
            name = str(stock.get("measurement", ""))
            if name and name not in seen:
                seen.append(name)
        return tuple(seen)

    def stock_role(self, measurement: str, tags: dict | None = None) -> dict | None:
        """The declared stock whose measurement and tags match, if any.

        Matched on the tags the caller actually filtered by: a query for
        `{Location: CleanWaterTank}` finds the clean-water stock, so the answer
        can say the fall is consumption rather than leaving it to the reader.
        """
        tags = tags or {}
        best: dict | None = None
        for stock in self.stocks:
            if str(stock.get("measurement", "")) != measurement:
                continue
            declared = stock.get("tags") or {}
            # Every tag the stock declares must be satisfied by the query.
            if all(str(tags.get(k, "")) == str(v) for k, v in declared.items()):
                # Prefer the most specific match (the most declared tags).
                if best is None or len(declared) > len(best.get("tags") or {}):
                    best = stock
        return best

    def noise_floor(self, measurement: str, field_name: str):
        """The deadband for one field, or None if not measured for it."""
        return self.noise_floors.get(measurement, {}).get(field_name)

    def unit_for(self, measurement: str, field_name: str) -> tuple[str, str]:
        """(unit, source) where source is 'known' or 'unknown'. Never guesses."""
        table = self.units.get(measurement)
        if table is not None and field_name in table:
            return table[field_name], "known"
        return "", "unknown"

    def is_internal(self, measurement: str) -> bool:
        """True for the database's own metrics rather than a habitat sensor."""
        return bool(self.internal_prefixes) and measurement.startswith(
            self.internal_prefixes
        )


def _profile_path() -> Path | None:
    """The habitat profile to load, or None when the operator named none.

    There is deliberately no default habitat. ATLAS does not belong to one
    mission, so an unset HABITAT_CONFIG means "no habitat declared" — units are
    reported as unrecorded and the dashboard is derived from the database —
    rather than quietly assuming somebody else's station.
    """
    configured = get_settings().habitat_config.strip()
    if not configured:
        return None
    path = Path(configured).expanduser()
    if not path.is_absolute():
        path = _BACKEND_ROOT / path
    return path


def _load(path: Path) -> HabitatProfile:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        log.warning(
            "Habitat profile not found at %s — running with no zone names or "
            "units. Set HABITAT_CONFIG or add the file.",
            path,
        )
        return HabitatProfile()
    except (OSError, yaml.YAMLError) as exc:
        log.warning("Could not read habitat profile %s: %s", path, exc)
        return HabitatProfile()

    if not isinstance(raw, dict):
        log.warning("Habitat profile %s is not a mapping — ignoring.", path)
        return HabitatProfile()

    units_raw = raw.get("units") or {}
    units: dict[str, dict[str, str]] = {
        str(measurement): {str(f): str(u) for f, u in (fields or {}).items()}
        for measurement, fields in units_raw.items()
        if isinstance(fields, dict)
    }

    floors_raw = raw.get("noise_floors") or {}
    noise_floors: dict[str, dict[str, float]] = {
        str(measurement): {str(f): float(v) for f, v in (fields or {}).items()}
        for measurement, fields in floors_raw.items()
        if isinstance(fields, dict)
    }

    tag_keys = raw.get("location_tag_keys")
    zone_names = raw.get("zone_names") or raw.get("zones") or {}

    log.info("Habitat profile: %s (%s)", raw.get("name", "habitat"), path.name)
    return HabitatProfile(
        name=str(raw.get("name") or "habitat"),
        location_tag_keys=(
            tuple(str(k) for k in tag_keys)
            if isinstance(tag_keys, list) and tag_keys
            else _DEFAULT_LOCATION_TAG_KEYS
        ),
        internal_prefixes=tuple(str(p) for p in (raw.get("internal_prefixes") or [])),
        zone_names={str(k): str(v) for k, v in zone_names.items()},
        units=units,
        non_summable_fields=tuple(
            str(f) for f in (raw.get("non_summable_fields") or [])
        ),
        aggregate_tag_values=tuple(
            str(v) for v in (raw.get("aggregate_tag_values") or [])
        ),
        noise_floors=noise_floors,
        electrical=dict(raw.get("electrical") or {}),
        stocks=tuple(
            dict(s) for s in (raw.get("stocks") or []) if isinstance(s, dict)
        ),
        non_room_locations=tuple(
            str(v) for v in (raw.get("non_room_locations") or [])
        ),
        tag_label_prefixes={
            str(k): str(v) for k, v in (raw.get("tag_label_prefixes") or {}).items()
        },
        dashboard_panels=tuple(
            dict(p) for p in (raw.get("dashboard_panels") or []) if isinstance(p, dict)
        ),
        mission_resources=tuple(
            dict(r) for r in (raw.get("mission_resources") or []) if isinstance(r, dict)
        ),
        day_start_offset_minutes=(
            int(raw["day_start_offset_minutes"])
            if raw.get("day_start_offset_minutes") is not None
            else None
        ),
        crew_log_meters=dict(raw.get("crew_log_meters") or {}),
        sql_mapping=dict(raw.get("sql_mapping") or {}),
    )


@lru_cache(maxsize=1)
def profile() -> HabitatProfile:
    """The process-wide habitat profile, loaded once."""
    path = _profile_path()
    if path is None:
        log.warning(
            "No HABITAT_CONFIG set — running with no habitat profile. Units "
            "will be reported as unrecorded and the dashboard derived from the "
            "database. Point HABITAT_CONFIG at a profile (see "
            "config/examples/) to name this habitat's rooms, units and meters."
        )
        return HabitatProfile()
    return _load(path)


def reset() -> None:
    """Forget the loaded profile. For tests that point at another file."""
    profile.cache_clear()
