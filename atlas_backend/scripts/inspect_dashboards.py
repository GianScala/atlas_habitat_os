"""Read the habitat's Grafana dashboards to learn its conventions.

The dashboards encode three things ATLAS would otherwise have to guess:

  1. WHICH DATASOURCE a given kind of data lives on (water, power, EVA ...).
  2. THE EXACT InfluxQL a panel runs — measurement, field, tags, aggregation.
  3. THE UNIT each value is rendered in, which InfluxDB itself does not store.

This is a learning tool, not a query path. ATLAS never answers from a
dashboard; we read them to find out where to point a real query, and what to
call the number when it comes back.

    python scripts/inspect_dashboards.py            # survey everything
    python scripts/inspect_dashboards.py water      # only matching dashboards
"""

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.errors import AtlasError  # noqa: E402
from app.datasource.grafana import (  # noqa: E402
    get_dashboard,
    list_dashboards,
    list_datasources,
)

# Grafana unit ids -> what to print in an answer. Extend as you meet new ones.
GRAFANA_UNITS = {
    "celsius": "°C", "fahrenheit": "°F", "humidity": "%", "percent": "%",
    "percentunit": "%", "lux": "lux", "pressurehpa": "hPa", "pressurembar": "mbar",
    "pressurepsi": "psi", "velocityms": "m/s", "watt": "W", "kwatt": "kW",
    "watth": "Wh", "kwatth": "kWh", "amp": "A", "volt": "V", "voltamp": "VA",
    "hertz": "Hz", "ppm": "ppm", "litre": "L", "liter": "L", "Litres": "L",
    "m3": "m³", "decibel": "dB", "sievert": "Sv", "microsievert": "µSv",
    "conppb": "ppb", "conppm": "ppm", "conμgm3": "µg/m³", "conugm3": "µg/m³",
    "radmsv": "mSv", "radgy": "Gy", "radsvh": "Sv/h", "%vol": "% vol",
    "radusvh": "µSv/h", "radpfu": "pfu", "pfu": "pfu",
    "Wm2": "W/m²", "mW/m2": "mW/m²", "degree": "°", "kelvin": "K",
    "lengthcm": "cm", "cm": "cm", "bps": "bps", "ms": "ms",
    "decbytes": "bytes", "decmbytes": "MB", "decgbytes": "GB", "h": "hours",
    "short": "", "none": "", "percentage": "%", "string": "",
}


def panels(node: dict) -> Iterator[dict]:
    """Walk a dashboard's panel tree, including panels nested inside rows."""
    for panel in node.get("panels", []) or []:
        if panel.get("type") == "row":
            yield from panels(panel)
        else:
            yield panel


def datasource_uid(obj: Any) -> str | None:
    """A panel or target's datasource uid, across Grafana's several formats."""
    source = obj.get("datasource")
    if isinstance(source, dict):
        return source.get("uid")
    if isinstance(source, str):
        return source
    return None


def builder_fields(target: dict) -> list[str]:
    """The field names a builder-mode target selects."""
    fields: list[str] = []
    for group in target.get("select") or []:
        for part in group:
            if part.get("type") == "field":
                fields.extend(str(p) for p in (part.get("params") or []))
    return fields


def target_query(target: dict) -> str | None:
    """The InfluxQL a target runs — raw if hand-written, else reconstructed."""
    if target.get("query") and target.get("rawQuery") is not False:
        return " ".join(str(target["query"]).split())

    measurement = target.get("measurement")
    if not measurement:
        return None

    tags = " AND ".join(
        f'{t.get("key")}{t.get("operator", "=")}{t.get("value")!r}'
        for t in target.get("tags") or []
    )
    shown = ", ".join(builder_fields(target)) or "*"
    return (
        f"[builder] SELECT {shown} FROM {measurement}"
        + (f" WHERE {tags}" if tags else "")
    )


def unit_of(panel: dict) -> str:
    raw = ((panel.get("fieldConfig") or {}).get("defaults") or {}).get("unit")
    if not raw:
        return ""
    return GRAFANA_UNITS.get(raw, raw)


def _collect_units(target: dict, unit: str, source: str, units: dict) -> None:
    """Record every (measurement, field) -> unit a panel renders.

    Units are only trustworthy from builder-mode targets, where measurement
    and field are structured data rather than something to scrape out of a
    query string. Flux and hand-written InfluxQL are skipped: one panel can
    select several fields with different units (Water.litres is litres,
    Water.water_height is centimetres), so guessing from the text produces
    confident nonsense.

    Every observation is kept rather than only the first. Panels do disagree
    — sometimes because they read the same-named measurement from a different
    datasource — and a first-one-wins rule hides exactly the cases where a
    human needs to look.
    """
    measurement = target.get("measurement")
    if not (unit and measurement) or target.get("query"):
        return
    for name in builder_fields(target) or ["value"]:
        units.setdefault((measurement, name), {}).setdefault(unit, set()).add(source)


def survey(filter_word: str | None = None) -> int:
    try:
        found = list_dashboards()
    except AtlasError as exc:
        print(f"FAILED: {exc.message}")
        return 1

    if filter_word:
        needle = filter_word.lower()
        found = [
            d
            for d in found
            if needle in d["title"].lower() or needle in d["folder"].lower()
        ]

    label = f" matching {filter_word!r}" if filter_word else ""
    print(f"{len(found)} dashboard(s){label}")

    try:
        uid_names = {d["uid"]: d["name"] for d in list_datasources()}
    except AtlasError:
        uid_names = {}

    seen_sources: dict[str, int] = {}
    # (measurement, field) -> unit -> the datasources that rendered it that way
    units: dict[tuple[str, str], dict[str, set[str]]] = {}

    for entry in sorted(found, key=lambda d: (d["folder"], d["title"])):
        try:
            board = get_dashboard(entry["uid"]).get("dashboard", {})
        except AtlasError as exc:
            print(f"\n[{entry['folder']}] {entry['title']}\n  could not read: {exc.message}")
            continue

        rows = []
        for panel in panels(board):
            panel_source = datasource_uid(panel)
            for target in panel.get("targets") or []:
                query = target_query(target)
                if not query:
                    continue
                uid = datasource_uid(target) or panel_source or "?"
                seen_sources[uid] = seen_sources.get(uid, 0) + 1
                unit = unit_of(panel)
                rows.append((panel.get("title") or "(untitled)", unit, uid, query))
                _collect_units(target, unit, uid_names.get(uid, uid), units)

        if not rows:
            continue

        print(f"\n[{entry['folder']}] {entry['title']}")
        for title, unit, uid, query in rows:
            print(f"  · {title}" + (f"  [{unit}]" if unit else ""))
            print(f"      via {uid_names.get(uid, uid)}")
            print(f"      {query[:300]}")

    print("\n" + "=" * 64)
    print("datasources actually used by these panels:")
    for uid, count in sorted(seen_sources.items(), key=lambda kv: -kv[1]):
        print(f"  {count:>4} panel target(s)  {uid_names.get(uid, uid)}  ({uid})")

    _print_units(units)
    return 0


def _print_units(units: dict[tuple[str, str], dict[str, set[str]]]) -> None:
    if not units:
        return

    agreed: dict[str, dict[str, str]] = {}
    disputed: list[tuple[str, str, dict[str, set[str]]]] = []

    for (measurement, field), observations in units.items():
        if len(observations) == 1:
            agreed.setdefault(measurement, {})[field] = next(iter(observations))
        else:
            disputed.append((measurement, field, observations))

    print("\nunits observed per measurement/field (paste into telemetry/units.py):")
    for measurement in sorted(agreed):
        body = ", ".join(f'"{f}": "{u}"' for f, u in sorted(agreed[measurement].items()))
        print(f'  "{measurement}": {{{body}}},')

    if not disputed:
        return

    # Panels disagreeing about a field is the case worth a human's attention,
    # so it is reported loudly and left out of the paste block above.
    print(f"\n  DISAGREEMENT — {len(disputed)} field(s) rendered inconsistently.")
    print("  These are NOT in the block above. Decide which applies to the")
    print("  datasource ATLAS actually queries, then add it by hand:\n")
    for measurement, field, observations in sorted(disputed):
        print(f"    {measurement}.{field}")
        for unit, sources in sorted(observations.items()):
            print(f"      {unit!r:<12} rendered by: {', '.join(sorted(sources))}")


if __name__ == "__main__":
    raise SystemExit(survey(sys.argv[1] if len(sys.argv) > 1 else None))
