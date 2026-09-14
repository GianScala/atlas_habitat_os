"""Gate 1: can we reach the habitat database at all?

    python scripts/check_connection.py

Passes when the last line reads OK. A large measurement count is expected:
habitat sensors plus InfluxDB's own internal metrics, which ATLAS filters out.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.core.errors import AtlasError  # noqa: E402
from app.datasource.grafana import (  # noqa: E402
    database_name,
    get_datasource,
    influxql,
    list_datasources,
)


def _print_datasources(datasources: list[dict], configured_uid: str) -> None:
    print(f"Found {len(datasources)} datasource(s):\n")
    for entry in datasources:
        marker = "  <- configured" if entry["uid"] == configured_uid else ""
        print(
            f"  id={entry['id']!s:<5} uid={entry['uid']!s:<24} "
            f"type={entry['type']!s:<12} db={entry['database']!s:<16} "
            f"name={entry['name']}{marker}"
        )


def main() -> int:
    settings = get_settings()

    print("ATLAS — Grafana proxy connection check")
    print("=" * 64)
    print(f"Grafana URL : {settings.grafana_base or '(unset)'}")
    print(f"Datasource  : {settings.grafana_datasource_uid or '(unset)'}")
    print()

    try:
        print("[1/3] Listing datasources ...")
        datasources = list_datasources()
        _print_datasources(datasources, settings.grafana_datasource_uid)

        print("\n[2/3] Resolving the configured datasource ...")
        datasource = get_datasource()
        database = database_name()
        print(
            f"  {datasource['name']} (type={datasource['type']}, "
            f"id={datasource['id']}) -> database {database!r}"
        )

        print("\n[3/3] Running: SHOW MEASUREMENTS")
        result = influxql("SHOW MEASUREMENTS")
        names = [row[0] for series in result["series"] for row in series["values"]]
        if not names:
            print("  Query succeeded but returned no measurements.")
        else:
            print(f"  {len(names)} measurement(s), first 12:")
            for name in names[:12]:
                print(f"    - {name}")

    except AtlasError as exc:
        print(f"\nFAILED: {exc.message}", file=sys.stderr)
        return 1

    print("\nOK — Grafana auth works and InfluxQL queries reach the database.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
