"""Gate 2: exercise the query helpers against live data.

Discovers the schema, prints readings with timestamps, then demonstrates both
aggregation modes. `-> no data` is a valid result, not a failure.

    python scripts/smoke_tools.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.errors import AtlasError  # noqa: E402
from app.telemetry.aggregation import get_consumption, summarize  # noqa: E402
from app.telemetry.discovery import describe, list_measurements  # noqa: E402
from app.telemetry.readings import get_latest, get_latest_all_phases  # noqa: E402
from app.telemetry.tanks import get_tank_flow  # noqa: E402

NOTABLE_KEYS = ("cumulative", "series_count", "note", "warning", "series_note")


def show(label: str, result: dict) -> None:
    print(f"\n{label}")
    print(f"  query: {result.get('query') or result.get('queries')}")

    data = result.get("data")
    if data is None:
        print("  -> no data")
        return
    if isinstance(data, dict) and "value" in data:
        print(f"  -> {data['value']} {result.get('unit', '')}  at {data['time']}")
    else:
        print(f"  -> {data}")

    for key in NOTABLE_KEYS:
        value = result.get(key)
        if value is not None and value != {}:
            print(f"  {key}: {value}")
    if result.get("matched_tag_values"):
        print(f"  matched_tag_values: {result['matched_tag_values']}")


def show_schema() -> None:
    print("\n--- schema, as the database reports it ---")
    for measurement in ("Temperature", "Electricity", "Water"):
        try:
            info = describe(measurement)
        except AtlasError as exc:
            print(f"\n{measurement}: could not describe — {exc.message}")
            continue

        print(f"\n{measurement}")
        print(f"  tag keys: {info['tag_keys']}")
        print(f"  fields:   {[f['field'] for f in info['fields']]}")
        if info.get("locations"):
            print(f"  locations: {info['locations']}")
        if info.get("case_variants"):
            print(f"  CASE VARIANTS: {info['case_variants']}")
        if info.get("other_tags"):
            print(f"  other tags: {info['other_tags']}")


def show_energy() -> None:
    energy = get_consumption("Electricity", field="totalForwardActiveEnergy", days=3)
    print("\nget_consumption('Electricity', 'totalForwardActiveEnergy', days=3)")
    print(f"  query: {energy['query']}")

    if energy["data"] is None:
        print("  -> no data")
        return

    for entry in energy["data"]["series"]:
        window = entry.get("whole_window") or {}
        print(
            f"  Phase {entry['tags'].get('Phase', '?')}: "
            f"{window.get('first')} -> {window.get('last')} "
            f"= {window.get('delta')} {energy['unit']}"
            f"  (cumulative={entry['cumulative']})"
        )

    if energy["cumulative"]:
        print(
            f"  TOTAL across {energy['series_count']} phase(s): "
            f"{energy['data']['total_all_series']} {energy['unit']}"
            f"   average/day: {energy['data']['average_per_period']} {energy['unit']}"
        )
    else:
        print(f"  {energy['warning']}")


def show_tanks() -> None:
    """The same water data read as a flow rather than as a net change.

    Worth printing next to the get_consumption block above: that one reports
    cumulative=false and no total, and this one answers the question.
    """
    flow = get_tank_flow("Water", field="litres", days=3)
    print("\nget_tank_flow('Water', 'litres', days=3)")
    print(f"  query: {flow['query']}")
    print(
        f"  resolution: {flow['resolution_minutes']}m   "
        f"deadband: {flow['deadband']} {flow['unit']} ({flow['deadband_source']})"
    )

    if flow["data"] is None:
        print("  -> no data")
        return

    for entry in flow["data"]["series"]:
        print(f"  {entry['summary'].split('. Quote')[0]}")
        print(
            f"    net from levels {entry['net_from_levels']} vs from movements "
            f"{entry['net_from_moves']} (unreconciled {entry['unreconciled']})"
        )


def main() -> int:
    print("ATLAS — query helper smoke test (runtime discovery)")
    print("=" * 64)

    try:
        found = list_measurements()
        print(f"\n{found['count']} habitat measurements discovered:")
        print("  " + ", ".join(found["data"] or []))
        print(f"  ({found['note']})")

        show_schema()

        print("\n--- readings ---")
        show("get_latest('Temperature', 'Atrium')", get_latest("Temperature", "Atrium"))
        show(
            "get_latest('Temperature', 'airlock')  [case variants]",
            get_latest("Temperature", "airlock"),
        )
        show(
            "get_latest('Electricity', field='current', phase='1')",
            get_latest("Electricity", field="current", phase="1"),
        )
        show("get_latest_all_phases('current')", get_latest_all_phases("current"))

        print("\n--- aggregation over time ---")
        show(
            "summarize('Temperature', 'Atrium', days=3, group_by='day')",
            summarize("Temperature", "Atrium", days=3, group_by="day"),
        )
        show_energy()
        show(
            "get_consumption('Water', 'litres', CleanWaterTank, days=3)",
            get_consumption(
                "Water", field="litres", tags={"Container": "CleanWaterTank"}, days=3
            ),
        )
        show_tanks()

    except AtlasError as exc:
        print(f"\nFAILED: {exc.message}")
        return 1

    print("\nOK — schema discovered at runtime, readings and aggregates returned.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
