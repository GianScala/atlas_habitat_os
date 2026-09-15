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
CORS_ORIGINS=http://127.0.0.1:5181 \
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
| `atlas-room-analysis.png` | Room analysis, 24 hours, all rooms, environment panels |

The sample Greenhouse readings are 100 and 112 kWh on MD-03, then 117 kWh the
next morning. The derived values are 12 kWh daytime, 5 kWh overnight, and
17 kWh for the day. MD-05's galley evening water reading is deliberately absent.

The seed data uses a rolling time window. These screenshots were captured on
2026-09-15; regenerating the example changes calendar dates and live totals.
The chat and room-analysis images were captured earlier than this consumption
walkthrough and are reused in the README and the assistant guide. The AI
screenshots below use the same synthetic telemetry, queried later on the
capture day.


## Capture the AI assistant

Start Ollama on the backend computer, then open **Settings → AI & models** and
select an installed model with tool support. These examples use `ministral-3:8b`
and `qwen3.5:9b` locally. Model selection is saved in the isolated application
database. No cloud model is used.

Keep `CORS_ORIGINS` set to the exact preview origin above so the backend accepts
chat and model-selection requests from the browser.

### Room comparison — Ministral 3 8B (optional)

This capture is not currently used in the docs; the assistant guide and README
use `atlas-chat.png` instead. Start a fresh chat with:

> Compare the latest temperature readings in the Greenhouse and Dormitory.
> Check the sensor names first, give a short table with units and UTC timestamps,
> and say which room is warmer.

Wait for the answer to finish and verify its readings against the returned data.
Capture the answer with its local model attribution. Expand Source for a view
of the references accompanying that answer.

### Water source analysis — Qwen 3.5 9B

Select `qwen3.5:9b` and start another chat:

> How much clean water did we use over the last 3 days? Check the available
> water sensors first, then distinguish consumption from refills. Give a
> concise daily table with units and sources.

Expand **what ATLAS read** after completion. The screenshot focuses on the
sensor discovery and successful clean/grey-water tool calls. Inspect the model's
answer separately: in this capture its first table omitted a partial day,
which is why the trace is useful evidence rather than proof that the answer is
correct. Follow-ups can refine the presentation, but still require checking.

Capture actual output; do not replace model text or tool results with a staged
answer. Model latency and response wording vary between runs.

| Image | View and state |
| --- | --- |
| `atlas-chat.png` | Completed clean-water answer with its Source panel expanded |
| `atlas-ai-sources.png` | Qwen's expanded water discovery and tank-flow trace |
| `atlas-local-models.png` | Local Ollama provider with Qwen selected and tool support visible |

The SQLite demo reports descriptive query summaries rather than executable SQL.
Keep the tool arguments visible alongside them. Relative windows move with the
query time, so rerunning the same question later can produce different totals.
