"""Build the demo SQLite habitat — proof that ATLAS runs with no InfluxDB.

    python scripts/seed_demo_sqlite.py

Writes config/examples/demo_habitat.db in ATLAS's canonical `readings` schema
(measurement, location, field, ts, value) with 30 days of synthetic telemetry for
a fictional station: a Greenhouse, a Robotics Bay, a Medical Bay, a Science
Lab, a Dormitory, Crew Quarters, and an Airlock.

It deliberately covers all three kinds of number ATLAS reasons about, so every
feature can be exercised offline:

  RATES     Temperature, Humidity, CO2, Power — per room, and not every room has
            every sensor, so discovery has something real to report.
  TOTALISERS Energy per room and for the habitat — climbing meters, for
            get_consumption and the mission plan.
  STOCKS    a clean water tank (SUPPLY: falls with use, jumps on delivery) and a
            grey water tank (WASTE: rises with use, drops when pumped out) — for
            get_tank_flow, the drawdown/fillup charts, and the deadband.

The data uses fixed random seeds in a rolling time window; each run shifts the
timestamps to the present. Existing files are preserved unless --force is given.
Then point ATLAS at it — see config/examples/demo_habitat.yaml.
"""

import argparse
import math
import random
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.datasource.sqlite import _SCHEMA  # noqa: E402

DB_PATH = Path(__file__).resolve().parents[1] / "config" / "examples" / "demo_habitat.db"

DAYS = 30
STEP_SECONDS = 600  # a reading every 10 minutes

# Which measurements each room reports, and how to synthesise a plausible value.
# (baseline, daily_swing, noise) for rate-style sensors; Energy is cumulative.
ROOMS = [
    "Greenhouse",
    "RoboticsBay",
    "MedicalBay",
    "ScienceLab",
    "Dormitory",
    "CrewQuarters",
    "Airlock",
]

# measurement -> field -> (baseline, daily swing amplitude, noise sd)
RATE_SENSORS = {
    "Temperature": {"value": (21.0, 2.5, 0.3)},
    "Humidity": {"value": (45.0, 8.0, 1.5)},
    "CO2": {"value": (650.0, 250.0, 40.0)},
    "Power": {"value": (400.0, 180.0, 30.0)},
}

# Per-room offsets so rooms differ believably (the greenhouse is warm and humid,
# the robotics bay draws more power, and so on).
ROOM_BIAS = {
    "Greenhouse": {"Temperature": +3.0, "Humidity": +25.0, "CO2": +150.0, "Power": +50.0},
    "RoboticsBay": {"Temperature": +1.0, "Humidity": -10.0, "CO2": -50.0, "Power": +350.0},
    "MedicalBay": {"Temperature": +0.5, "Humidity": 0.0, "CO2": -20.0, "Power": +40.0},
    "ScienceLab": {"Temperature": 0.0, "Humidity": -5.0, "CO2": +30.0, "Power": +120.0},
    "Dormitory": {"Temperature": +1.5, "Humidity": +8.0, "CO2": +260.0, "Power": +60.0},
    "CrewQuarters": {"Temperature": +1.5, "Humidity": +5.0, "CO2": +200.0, "Power": +80.0},
    "Airlock": {"Temperature": -4.0, "Humidity": -15.0, "CO2": -100.0, "Power": -50.0},
}

# Not every room has every sensor — habitats are heterogeneous, and ATLAS must
# discover that rather than assume it.
SENSORS_BY_ROOM = {
    "Greenhouse": ["Temperature", "Humidity", "CO2", "Power", "Energy"],
    "RoboticsBay": ["Temperature", "Power", "Energy"],
    "MedicalBay": ["Temperature", "Humidity", "CO2", "Power", "Energy"],
    "ScienceLab": ["Temperature", "CO2", "Power", "Energy"],
    "Dormitory": ["Temperature", "Humidity", "CO2", "Power", "Energy"],
    "CrewQuarters": ["Temperature", "Humidity", "CO2", "Power", "Energy"],
    "Airlock": ["Temperature", "Power", "Energy"],
}


# --- Water ------------------------------------------------------------------
#
# The two tanks every habitat has, and the reason ATLAS has a tank tool at all.
# They are STOCKS: the reading is a level and the MOVEMENT is the flow.
#
#   CleanWaterTank  a SUPPLY tank. Falls as the crew draws from it, and jumps
#                   when a delivery refills it. Its FALL is consumption; the net
#                   change is not, which is exactly the trap get_tank_flow and
#                   the drawdown chart exist to avoid.
#   GreyWaterTank   a WASTE tank. Rises as the habitat produces waste water, and
#                   drops when it is pumped out. Its RISE is production.
#
# Both gauges also carry a little dither, so the demo exercises the deadband
# that keeps a still tank from reporting phantom consumption.
CLEAN_TANK_CAPACITY = 2000.0
CLEAN_TANK_START = 1650.0
CLEAN_REFILL_TO = 1900.0
CLEAN_REFILL_AT = 900.0          # litres: a delivery is called when it gets low
GREY_TANK_START = 240.0
GREY_EMPTY_AT = 1200.0           # litres: pumped out when it fills up
GREY_EMPTY_TO = 150.0
GAUGE_NOISE = 0.35               # litres of dither, under the 1 L deadband

# Litres per person-step of draw, shaped by the hour: the crew uses water when
# they are awake, and most of it around the morning and evening.
BASE_DRAW_PER_STEP = 1.1
# Roughly this share of the clean water drawn comes back as grey water; the rest
# leaves as vapour, plant uptake, and what the greenhouse keeps.
GREY_RETURN_FRACTION = 0.82


def _water_demand(hour_fraction: float, rng: random.Random) -> float:
    """Litres drawn in one step, shaped by the time of day."""
    # Two humps — a morning peak and a larger evening one — on a low night floor.
    morning = math.exp(-(((hour_fraction - 0.32) / 0.06) ** 2))
    evening = math.exp(-(((hour_fraction - 0.80) / 0.09) ** 2))
    awake = 0.15 + 1.6 * morning + 2.1 * evening
    return max(0.0, BASE_DRAW_PER_STEP * awake * rng.uniform(0.5, 1.5))


def _rows():
    rng = random.Random(1729)
    now = int(time.time())
    start = now - DAYS * 86400
    steps = list(range(start, now, STEP_SECONDS))

    for room in ROOMS:
        energy = rng.uniform(100, 400)  # starting kWh on the room's totaliser
        for ts in steps:
            hour = (ts % 86400) / 86400.0
            daylight = math.sin(2 * math.pi * (hour - 0.25))  # peak mid-afternoon

            for measurement in SENSORS_BY_ROOM[room]:
                if measurement == "Energy":
                    # A cumulative meter that only ever climbs — for get_consumption.
                    load_kw = (RATE_SENSORS["Power"]["value"][0]
                               + ROOM_BIAS[room].get("Power", 0.0)) / 1000.0
                    energy += max(0.0, load_kw * (STEP_SECONDS / 3600.0)
                                  * rng.uniform(0.8, 1.2))
                    yield (measurement, room, "total_kwh", float(ts), round(energy, 4))
                    continue

                base, swing, noise = RATE_SENSORS[measurement]["value"]
                bias = ROOM_BIAS[room].get(measurement, 0.0)
                value = base + bias + swing * daylight + rng.gauss(0, noise)
                if measurement in ("Humidity",):
                    value = max(0.0, min(100.0, value))
                if measurement in ("CO2", "Power"):
                    value = max(0.0, value)
                yield (measurement, room, "value", float(ts), round(value, 3))

    # --- the two water tanks, walked forward together ----------------------
    water_rng = random.Random(4242)
    clean = CLEAN_TANK_START
    grey = GREY_TANK_START
    for ts in steps:
        hour = (ts % 86400) / 86400.0
        drawn = _water_demand(hour, water_rng)

        clean = max(0.0, clean - drawn)
        if clean <= CLEAN_REFILL_AT:
            clean = CLEAN_REFILL_TO  # a delivery arrives: a step UP, not use
        grey += drawn * GREY_RETURN_FRACTION
        if grey >= GREY_EMPTY_AT:
            grey = GREY_EMPTY_TO  # pumped out: a step DOWN, not production

        yield (
            "Water", "CleanWaterTank", "litres", float(ts),
            round(min(CLEAN_TANK_CAPACITY, clean) + water_rng.gauss(0, GAUGE_NOISE), 3),
        )
        yield (
            "Water", "GreyWaterTank", "litres", float(ts),
            round(grey + water_rng.gauss(0, GAUGE_NOISE), 3),
        )

    # --- the whole-habitat electricity meter --------------------------------
    #
    # A second, independent account of power: the mains meter on the wall, which
    # the per-room submeters should come in a little UNDER (there are loads no
    # room owns). Tagged `Habitat`, which the profile declares a rollup so it is
    # never charted beside the rooms nor summed with them.
    mains_rng = random.Random(99)
    total_kwh = 5120.0
    room_load_w = sum(
        RATE_SENSORS["Power"]["value"][0] + ROOM_BIAS[room].get("Power", 0.0)
        for room in ROOMS
    )
    for ts in steps:
        hour = (ts % 86400) / 86400.0
        daylight = math.sin(2 * math.pi * (hour - 0.25))
        # Rooms, plus the shared plant no room owns (ventilation, pumps, comms).
        draw_w = max(
            0.0,
            room_load_w * 1.12 + 240.0 + 180.0 * daylight + mains_rng.gauss(0, 45),
        )
        total_kwh += (draw_w / 1000.0) * (STEP_SECONDS / 3600.0)
        yield ("Power", "Habitat", "value", float(ts), round(draw_w, 3))
        yield ("Energy", "Habitat", "total_kwh", float(ts), round(total_kwh, 4))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="Replace the existing demo database"
    )
    args = parser.parse_args()
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        if not args.force:
            print("Demo database already exists; use --force to regenerate synthetic data.")
            return 0
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(_SCHEMA)
        rows = list(_rows())
        conn.executemany(
            "INSERT INTO readings (measurement, location, field, ts, value) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
        measurements = conn.execute(
            "SELECT COUNT(DISTINCT measurement) FROM readings"
        ).fetchone()[0]
    finally:
        conn.close()

    print(f"Wrote {len(rows):,} readings to {DB_PATH}")
    print(f"  {measurements} measurements across {len(ROOMS)} rooms, {DAYS} days")
    print("\nRun ATLAS against it with:")
    print("  DATA_SOURCE=sqlite \\")
    print(f"  SQLITE_PATH=config/examples/{DB_PATH.name} \\")
    print("  HABITAT_CONFIG=config/examples/demo_habitat.yaml \\")
    print("  .venv/bin/python -m uvicorn app.main:app --reload")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
