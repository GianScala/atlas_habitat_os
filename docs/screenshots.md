# Documentation screenshots

The consumption screenshots are real captures of ATLAS using synthetic data.
They contain a 14-day mission, a planned water extra, complete power rounds,
and one deliberately missing water round. No real mission data is needed.

## Create an isolated example

After installing backend and frontend dependencies, run from `atlas_backend`:

```bash
.venv/bin/python scripts/seed_docs_demo.py /tmp/atlas-docs
```

Choose a new output directory each time; the script refuses to overwrite an
existing one. It creates separate telemetry and application databases, using
the demo habitat profile. It does not modify `.env` or an existing database.

Start the backend from the same directory:

```bash
DATA_SOURCE=sqlite \
SQLITE_PATH=/tmp/atlas-docs/telemetry.db \
DATABASE_PATH=/tmp/atlas-docs/app.db \
HABITAT_CONFIG=config/examples/demo_habitat.yaml \
KNOWLEDGE_DIR=/tmp/atlas-docs/knowledge \
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8011
```

In a second terminal, from `atlas_frontend`:

```bash
VITE_API_TARGET=http://127.0.0.1:8011 npm run dev -- --host 127.0.0.1 --port 5181
```

Open [the demo dashboard](http://127.0.0.1:5181/dashboard). No language model is
needed for these views. Stop both processes with Ctrl+C after capturing.

## Capture checklist

Wait for charts to finish loading and use a consistent theme. Keep the units,
legends, coverage notices, and relevant headings visible. Capture focused
sections at readable size instead of shrinking a full page into one image.

| Image | View and state |
| --- | --- |
| `atlas-dashboard.png` | Habitat consumption, 24 hours, water panels |
| `atlas-mission-plan.png` | Mission plan, clean-water budget cards |
| `atlas-daily-consumption.png` | Mission plan, clean-water Day by day chart |
| `atlas-daily-plan.png` | Mission plan, clean-water Every day expanded |
| `atlas-crew-log.png` | Crew meter log, Power, overview and coverage |
| `atlas-manual-daily.png` | Power, Day by day chart showing daytime and overnight use |
| `atlas-manual-readings.png` | Power → The sheet → One day → MD-03 |
| `atlas-water-log.png` | Water, overview showing the missing galley round |

The sample Greenhouse readings are 100 and 112 kWh on MD-03, then 117 kWh the
next morning. The derived values are 12 kWh daytime, 5 kWh overnight, and
17 kWh for the day. MD-05's galley evening water reading is deliberately absent.

The seed data uses a rolling time window. These screenshots were captured on
2026-09-15; regenerating the example changes calendar dates and live totals.
The older chat and room-analysis images are retained separately from this
consumption walkthrough.
