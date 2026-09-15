"""Create isolated synthetic telemetry, a mission, and manual readings for docs.

Run from atlas_backend: .venv/bin/python scripts/seed_docs_demo.py /tmp/atlas-docs
The output directory must not exist. No existing app or telemetry data is used.
"""

import os
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: seed_docs_demo.py NEW_OUTPUT_DIRECTORY")
    output = Path(sys.argv[1]).expanduser().resolve()
    try:
        output.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise SystemExit(f"{output} already exists. Choose a new output directory.") from None
    backend = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(backend))
    os.environ.update(
        DATA_SOURCE="sqlite",
        SQLITE_PATH=str(output / "telemetry.db"),
        DATABASE_PATH=str(output / "app.db"),
        HABITAT_CONFIG=str(backend / "config/examples/demo_habitat.yaml"),
        KNOWLEDGE_DIR=str(output / "knowledge"),
    )

    from seed_demo_sqlite import _rows

    from app.datasource.sqlite import _SCHEMA
    from app.mission import repository as repo
    from app.mission.plan import validate_extra, validate_mission
    from app.storage.database import initialise

    with sqlite3.connect(output / "telemetry.db") as connection:
        connection.executescript(_SCHEMA)
        connection.executemany(
            "INSERT INTO readings (measurement, location, field, ts, value) "
            "VALUES (?, ?, ?, ?, ?)",
            _rows(),
        )
    initialise()
    today = datetime.now(UTC).date()
    mission = validate_mission(
        "Aster Station · synthetic demo", (today - timedelta(days=6)).isoformat(), 14
    )
    repo.save_mission(mission)
    repo.save_day_start(0)
    repo.save_totals({"water": 2100, "power": 1680})
    repo.add_extra(validate_extra({
        "resource": "water", "label": "Greenhouse experiment", "amount": 180,
        "kind": "once", "mission_day": 10, "note": "Synthetic planned activity",
    }, mission))

    # Cumulative dials. MD-03 power is 100 -> 112 -> 117 for the Greenhouse.
    # Keep water's MD-05 galley evening absent to demonstrate missing coverage.
    for resource, meters in {
        "power": [("greenhouse", 66, 12, 5), ("robotics_bay", 250, 18, 7),
                  ("dormitory", 500, 5, 3)],
        "water": [("shower_warm", 10, .024, .008),
                  ("shower_cold", 20, .016, .006),
                  ("galley_cold", 30, .030, .012)],
    }.items():
        for meter, baseline, daytime, overnight in meters:
            for day in range(1, 8):
                morning = baseline + (day - 1) * (daytime + overnight)
                repo.save_reading(resource, meter, day, "morning", round(morning, 4))
                if day < 7 and not (meter == "galley_cold" and day == 5):
                    repo.save_reading(resource, meter, day, "evening",
                                      round(morning + daytime, 4))
    print(f"Created synthetic documentation data in {output}")


if __name__ == "__main__":
    main()
