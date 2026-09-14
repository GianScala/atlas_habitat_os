"""Find where the habitat telemetry actually lives.

Run this when the connection check succeeds but SHOW MEASUREMENTS comes back
with InfluxDB's own internal metrics instead of Temperature, Humidity, and
friends — that means we are pointed at the wrong datasource or database.

Sweeps every InfluxDB datasource Grafana knows about, and every database
inside each, and reports which hold the measurements we expect.

    python scripts/discover_datasources.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.errors import AtlasError  # noqa: E402
from app.datasource.grafana import influxql, list_datasources  # noqa: E402

# The measurements the dashboards told us to expect.
WANTED = {"Electricity", "Temperature", "Humidity", "Luminosity", "Pressure", "Wind"}


def measurements_in(database: str, uid: str) -> list[str]:
    result = influxql("SHOW MEASUREMENTS", db=database, uid=uid)
    return [row[0] for series in result["series"] for row in series["values"]]


def databases_in(uid: str) -> list[str]:
    # SHOW DATABASES still needs some db in the query string; any value works.
    result = influxql("SHOW DATABASES", db="_internal", uid=uid)
    return [row[0] for series in result["series"] for row in series["values"]]


def main() -> int:
    print("ATLAS — datasource discovery sweep")
    print("=" * 64)

    try:
        datasources = list_datasources()
    except AtlasError as exc:
        print(f"FAILED: {exc.message}")
        return 1

    influx = [d for d in datasources if (d["type"] or "").startswith("influx")]
    print(f"\n{len(datasources)} datasource(s), {len(influx)} of them InfluxDB:\n")
    for entry in datasources:
        print(
            f"  id={entry['id']!s:<5} uid={entry['uid']!s:<22} "
            f"type={entry['type']!s:<12} db={entry['database']!s:<18} "
            f"name={entry['name']}"
        )

    hits: list[tuple[str, str, str, list[str]]] = []

    for entry in influx:
        print(f"\n{'-' * 64}\nDatasource {entry['name']!r} (uid={entry['uid']})")

        try:
            databases = databases_in(entry["uid"])
        except AtlasError as exc:
            print(f"  SHOW DATABASES failed: {exc.message}")
            # Still worth trying whatever database Grafana has configured.
            databases = [entry["database"]] if entry["database"] else []

        if not databases:
            print("  No databases found.")
            continue

        print(f"  databases: {', '.join(databases)}")

        for database in databases:
            if database == "_internal":
                continue
            try:
                names = measurements_in(database, entry["uid"])
            except AtlasError as exc:
                print(f"    {database:<22} query failed: {exc.message[:90]}")
                continue

            found = sorted(WANTED.intersection(names))
            flag = f"  <== HABITAT DATA: {', '.join(found)}" if found else ""
            print(f"    {database:<22} {len(names):>4} measurement(s){flag}")
            if not found and names:
                preview = ", ".join(names[:6]) + (" ..." if len(names) > 6 else "")
                print(f"      {preview}")
            if found:
                hits.append((entry["name"], entry["uid"], database, names))

    print(f"\n{'=' * 64}")
    if not hits:
        print("No database contained the expected habitat measurements.")
        return 1

    print("Habitat telemetry found in:\n")
    for name, uid, database, names in hits:
        print(f"  datasource {name!r} (uid={uid}), database {database!r}")
        print(f"    all measurements: {', '.join(sorted(names))}\n")

    best = hits[0]
    print("Put these in your .env:\n")
    print(f"  GRAFANA_DATASOURCE_UID={best[1]}")
    print(f"  INFLUX_DB={best[2]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
