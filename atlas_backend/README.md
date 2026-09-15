# ATLAS backend

FastAPI service for telemetry queries, streamed chat, mission budgets, and
manual meter logs. Telemetry access is read-only; ATLAS stores conversations,
settings, plans, and manual readings in its own SQLite database.

## Run locally

Requires Python 3.11+. From this directory:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/python scripts/seed_demo_sqlite.py
.venv/bin/python -m uvicorn app.main:app --reload
```

API: [localhost:8000](http://localhost:8000). Interactive endpoint documentation:
[localhost:8000/docs](http://localhost:8000/docs).

The template selects synthetic SQLite telemetry. Charts and mission tracking
work without an LLM. For chat, start Ollama and select a model in
**Settings → AI & models**, or configure Anthropic. See
[configuration](../docs/configuration.md) for environment variables and profiles.

## Checks

```bash
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
```

`GET /api/health` checks local configuration; `GET /api/health/datasource`
checks the live connection. `scripts/check_connection.py`,
`scripts/discover_datasources.py`, and `scripts/inspect_dashboards.py` are
Grafana diagnostics, not general SQLite setup checks.

## Source map

| Directory under `app/` | Responsibility |
| --- | --- |
| `datasource/` | Discovery, structured queries, and database adapters |
| `habitat/` | Habitat profile, names, units, and resource definitions |
| `telemetry/` | Aggregation, cumulative usage, and tank flow |
| `mission/` | Plan storage, allowances, tracking, and manual meter calculations |
| `tools/` | Assistant tool schemas and dispatch |
| `llm/` | Ollama and Anthropic providers |
| `services/` | Agent loop, prompt, dashboard, settings, and supporting services |
| `api/routes/`, `schemas/` | HTTP endpoints and request/response contracts |
| `storage/` | Application database and conversation persistence |

## Query flow

```text
API or assistant tool → telemetry function → Query → DataSource adapter → database
```

The model calls semantic tools; it does not write SQL. Core code builds a
structured `Query`, and the adapter translates it for SQLite, mapped SQL,
InfluxDB, or Grafana. Keep adapter imports inside `datasource/`.

SQLite is the default adapter. Mapped SQL supports PostgreSQL, MySQL, and
TimescaleDB through a profile's `sql_mapping` and the appropriate driver.
Measurement names, fields, and tag values are discovered from the database.
The habitat profile supplies units and names that discovery cannot establish.
Tools for tanks and phased electrical meters depend on profile configuration.

See [adapter development](../README.md#writing-a-new-data-source-adapter).

## Consumption calculations

| Reading type | Tool | Calculation |
| --- | --- | --- |
| Instantaneous level or rate, such as temperature or power | `summarize` | Mean, minimum, maximum, or count per interval |
| Cumulative energy counter | `get_consumption` | Change in the counter, checked for decreases |
| Tank level that rises and falls | `get_tank_flow` | Falls and rises tracked separately |

A clean tank's fall represents use; its rise represents refill. For a waste
tank, the rise represents production and the fall represents emptying. Net
level change alone does not measure consumption. Tank analysis uses averaging,
a deadband for noise, and confirmation of the newest interval; recent use may
therefore appear with a delay.

Compute usage per series before combining meters or phases. Do not add an
already-aggregated total to its component phases. Keep units, query sources,
coverage warnings, and missing readings in responses.

## Mission plans and manual readings

`mission/dayplan.py` allocates a total budget across mission days and scheduled
extras. Extras reserve budget; they do not increase the total. Tracking uses a
single daily breakdown per resource to build today, cycle, and mission totals.
The plan's fixed UTC offset defines its day boundary.

Budget cards compare recorded use with both the full allowance and the amount
planned by now. Future daily allowances reflect recorded spending and remaining
extras. Missing telemetry makes consumption a lower bound, not a complete total.
Chat's general consumption tools use UTC days unless an offset is supplied;
mission tracking uses the saved mission boundary.

`mission/logbook.py` calculates manual consumption from cumulative dial readings:
evening minus morning for daytime, next morning minus evening for overnight.
Water entry units can differ from displayed consumption units. Missing or
backwards readings remain explicit; they are not replaced by estimates.

The manual log is independent of telemetry. Its readings do not overwrite
sensors, fill tracking gaps, or count as extra consumption in the mission plan.
See the [consumption guide](../docs/consumption-guide.md) for examples.

The assistant receives plan context through `mission/brief.py`; live plan
tracking comes through its query tool. Keep changing consumption figures out
of static prompt context.

## API overview

The generated `/docs` page is the complete reference, including body schemas.

| Endpoint family | Purpose |
| --- | --- |
| `/api/chat` | Stream an answer; supply `conversation_id` for a follow-up |
| `/api/conversations` | Read or delete stored conversations |
| `/api/dashboard` | Chart panels and range presets |
| `/api/mission/plan`, `/api/mission/tracking` | Edit the plan and read usage against it |
| `/api/mission/extras` | Create, edit, and remove planned extras |
| `/api/mission/log`, `/api/mission/log/reading` | Read manual analysis and save dial readings |
| `/api/settings` | Assistant preferences and other settings |
| `/api/models` | List, select, install, and remove models |
| `/api/meta` | Discover measurements, zones, and starter questions |
| `/api/voice` | Voice readiness, settings, transcription, and synthesis |
| `/api/health`, `/api/health/datasource` | Configuration and connection health |

Chat uses SSE (`text/event-stream`) with JSON `data:` records: `start`,
`thinking_delta`, `text_delta`, `tool_call`, `tool_result`, `sources`, `error`,
and `done`. Source queries use the active adapter's dialect. Keep backend
schemas and frontend `src/lib/types.ts` in sync.

## Models and storage

Ollama runs inference locally. Anthropic sends questions, conversation context,
and retrieved data to the cloud. Saved UI model choices override environment
fallbacks. The assistant is instructed to cite queried readings, but those rules
do not guarantee a correct answer.

`DATABASE_PATH` is the application database; `SQLITE_PATH` is telemetry.
`KNOWLEDGE_DIR` stores uploaded context files. Back up application data before
changing mission dates or storage configuration. Refresh discovery with
`POST /api/meta/refresh` after adding sensors.

## Optional offline voice

The microphone path is local end to end: the browser records audio, the backend
converts it with `ffmpeg`, whisper.cpp transcribes it, and Piper renders the
answer to WAV. No hosted speech API is called. Read aloud appears beneath every
answer, including saved conversations. Voice-entered questions also opt into
automatic playback, with an explicit Play audio button if the browser blocks it.

Install [whisper.cpp](https://github.com/ggml-org/whisper.cpp), `ffmpeg`, and
[Piper](https://github.com/OHF-Voice/piper1-gpl). Download one whisper.cpp model
and one Piper ONNX voice whose license suits your distribution, then set:

```dotenv
VOICE_WHISPER_MODEL=models/ggml-tiny.bin
VOICE_WHISPER_LANGUAGE=auto
VOICE_PIPER_MODEL=models/en_US-lessac-medium.onnx
```

Install `requirements-voice.txt` into the backend virtual environment to keep
Piper loaded between answers (`python -m pip install -r requirements-voice.txt`).
The separately installed Piper CLI remains a fallback. The fast default uses
multilingual Whisper tiny on CPU, single-candidate decoding without repeated
temperature retries, and trims quiet recording edges. It trades some recognition
accuracy for speed; a larger multilingual model can be selected via
`VOICE_WHISPER_MODEL`. Actual latency depends on clip length and CPU load.

Put each additional Piper `.onnx` and matching `.onnx.json` file in `models/`.
AI & models → Voice & dictation lists installed voices, provides a preview, and
saves the chosen voice and dictation language. Only offline eSpeak voices are
offered; phonemizers that may fetch auxiliary models are excluded. Voice model
licenses are independent of Piper's license and should be checked before use.

The models are optional, git-ignored, and are not bundled with ATLAS. The mic
remains visible but disabled until transcription tools are ready;
`/api/voice/status` reports which half is available. Serve the frontend over HTTPS outside localhost,
because browsers require a secure context before granting microphone access.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| No sensor data | Adapter settings, connectivity, profile, and selected time range |
| Demo charts are empty | The seed data may be old; regenerate the synthetic database with `--force` |
| Ollama is unavailable | Start the daemon and check `OLLAMA_HOST` |
| A model is not installed | Install or select one in Settings → AI & models |
| Missing units or unfamiliar room names | Profile `units` and `zone_names`, or Database nomenclature settings |
| Mission comparisons are missing | Save a mission and resource budgets first |
| A manual total is incomplete | Check both endpoint readings for each meter and interval |
| Grafana authentication or datasource errors | Credentials, permissions, and datasource UID |

For remote hosting, follow [deployment](../docs/deployment.md) and
[security](../SECURITY.md). The app assumes a trusted crew behind shared access
controls; the telemetry database should use read-only credentials.
