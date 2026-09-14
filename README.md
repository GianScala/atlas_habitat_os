# ATLAS - a habitat-agnostic telemetry assistant for analog space missions

Created and maintained by **Gianmarco Scalabrin**, the project’s main contributor.
Community contributions are welcome.

**Release scope:** a shared application for a trusted crew, with synthetic demo
data. Remote deployments require authentication in front of the whole site.
See [deployment](docs/deployment.md), [security and privacy](SECURITY.md),
[contribution guidelines](CONTRIBUTING.md) and [release status](docs/release-readiness.md).
Lunares data and private mission configurations must never be included in this
repository. Public source code does not make an operational instance public-safe.


Ask questions about your analog space habitat's telemetry in plain English.
ATLAS queries habitat telemetry while you wait and asks the model to cite its
sources. Model answers can still be wrong; check the cited readings before
using an answer for an operational decision.

ATLAS is built to be **deployed by any analog mission**, not one habitat. Which
database it reads, what its rooms are called, and what units its sensors carry
are all *configuration* — a data-source adapter and a habitat profile — not code
you have to fork.

```
atlas_analog_habitats/
├── atlas_backend/    FastAPI service — the agent loop, data-source adapters,
│                      and habitat data access
└── atlas_frontend/   React + TypeScript chat, dashboard, and mission views
```

The model that reads the telemetry and writes the answer **runs on this machine**
by default, under [Ollama](https://ollama.com/download) — no API key, nothing
about a question leaving the habitat. Claude over the Anthropic API is one click
away on the Models page if you want it.

---

## The problem it solves

An analog habitat is wired with dozens of sensors streaming into a time-series
database, usually behind Grafana. The data is all there, but *asking* it a
question means writing a query, knowing the schema, and knowing which meter is
which. During a mission nobody has time for that.

ATLAS puts a grounded natural-language layer in front of that database. The crew
asks "how much water did we use yesterday?" and gets a cited figure, run live,
with the query shown. It refuses to guess: if a sensor isn't there, it says what
it searched; if a unit isn't recorded, it gives the bare number rather than
inventing a dimension.

## Main use cases

- **In-mission situational awareness** — power, water, air quality, per-room
  conditions, "are we on plan?", asked conversationally.
- **Consumption against a declared mission plan** — budgets and allowances the
  crew set, compared to what was actually drawn.
- **A reusable platform** — a new analog mission points ATLAS at its own
  database with an adapter and a habitat profile, and gets the same assistant.

## Who it's for

- **Analog missions** deploying ATLAS for their own habitat (start with
  [Deploying for your mission](#deploying-atlas-for-your-mission)).
- **Contributors** extending it — new data-source adapters, new query
  capabilities (start with [Extending ATLAS](#extending-atlas)).

---

## High-level architecture

The core application never talks to a database directly. It talks to a
**data-source interface**, and an **adapter** behind that interface does the
actual connecting. Grafana is one adapter, not a dependency.

```
   ┌─────────────────────────────────────────────────────────┐
   │  ATLAS Core                                             │
   │  agent loop · tools · telemetry (builds a Query)         │
   └───────────────────────────┬─────────────────────────────┘
                               │  run(Query) -> series   (+ discovery)
                   ┌───────────▼───────────┐
                   │  DataSource interface  │   app/datasource/base.py
                   └───────────┬───────────┘
             ┌─────────────────┼───────────────────┐
             ▼                 ▼                   ▼
     ┌───────────────┐ ┌───────────────┐ ┌───────────────────┐
     │ Grafana proxy │ │ InfluxDB      │ │ SQLite / your      │
     │ (InfluxQL)    │ │ (InfluxQL)    │ │ adapter (any DB)   │
     └───────┬───────┘ └───────┬───────┘ └─────────┬─────────┘
             ▼                 ▼                   ▼
        Habitat Grafana   Habitat InfluxDB    SQLite / Postgres / …
```

The seam is a **structured, dialect-neutral `Query`** — a measurement, a field,
an aggregate, a time window — not a query string. Each adapter renders it into
its own language (InfluxQL for the InfluxDB adapters, SQL for SQLite), so the
telemetry layer, the tools, and the API are identical whatever backend answers.

Two things are configuration, loaded at startup, editable without touching core
code:

| What | Where | Chosen by |
| --- | --- | --- |
| **Which database** and how to reach it | `app/datasource/` adapters | `DATA_SOURCE` + connection env vars |
| **What the habitat is** — rooms, units, tag names, display name | `config/examples/*.yaml` (a *habitat profile*) | `HABITAT_CONFIG` |

Everything discoverable — the measurement names, the fields, the tag values — is
still read live from the database at runtime and is never hardcoded.

### How the model talks to the database

The model never writes a query. It calls a **semantic tool API** —
`get_latest`, `summarize`, `get_consumption`, and so on — and the telemetry
layer turns each call into a structured `Query`. The InfluxDB adapters render
that `Query` to InfluxQL; the SQLite adapter renders it to SQL and aggregates in
Python. Adding a backend means teaching one adapter to render the `Query` in its
own dialect — see
[Writing a new data-source adapter](#writing-a-new-data-source-adapter).

Every read path — including the dashboard charts and tank-flow analysis — runs
through the structured `Query`, so all of it works on any adapter. The tool set
itself is **habitat-driven**: `get_tank_flow` is offered only when the habitat
profile declares `stocks`, and `get_latest_all_phases` only when it
declares an `electrical` meter, so a mission with neither gets a clean,
applicable tool set from configuration alone.

---

## Repository structure

```
atlas_backend/
├── app/
│   ├── datasource/        the data-source seam — Grafana never leaks past here
│   │   ├── base.py          the DataSource interface
│   │   ├── wire.py          shared InfluxDB read-only + response parsing
│   │   ├── grafana.py       Grafana-proxy adapter (the reference/default)
│   │   ├── influxdb.py      direct InfluxDB 1.x adapter
│   │   └── __init__.py      the registry: influxql() + get_data_source()
│   ├── habitat/           the habitat profile loader (zones, units, names)
│   ├── telemetry/         builds InfluxQL, parses series; no transport knowledge
│   ├── tools/             the model's vocabulary, bound to telemetry functions
│   ├── mission/           the crew's plan and hand-read meter log (SQLite)
│   ├── llm/               model providers: Ollama (local) and Anthropic (cloud)
│   ├── services/          the agent loop, the system prompt, the dashboard
│   ├── api/               FastAPI routes
│   ├── storage/           chat-history persistence (SQLite)
│   └── config.py          all configuration, read once from the environment
├── config/examples/      habitat profiles — habitat.example.yaml documents them all
├── scripts/              connection/diagnostic scripts (Grafana-specific)
└── tests/                unit tests, no network required

atlas_frontend/          React + TypeScript (Vite) — chat, dashboard, mission
```

Each half has its own README with component-level detail
([backend](atlas_backend/README.md), [frontend](atlas_frontend/README.md)).
This document is the entry point.

---

## Installation

Prerequisites: **Python 3.11+**, **Node 22.12+**, and (for the default local model)
**[Ollama](https://ollama.com/download)**.

**Backend**

```bash
cd atlas_backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/python scripts/seed_demo_sqlite.py  # generate synthetic demo telemetry
```

**Frontend**

```bash
cd atlas_frontend
npm install
```

**The model runtime** (default is a local model, so no API key)

```bash
# Install once: https://ollama.com/download
ollama serve              # or just open the Ollama app
```

Nothing needs pulling by hand — the Models page installs whatever model you pick.

---

## Local development

Two terminals:

```bash
# terminal 1 — backend (hot reload)
cd atlas_backend && .venv/bin/python -m uvicorn app.main:app --reload
```

```bash
# terminal 2 — frontend (hot reload)
cd atlas_frontend && npm run dev
```

Open `http://localhost:5173`.

Before the first chat, check the plumbing:

```bash
cd atlas_backend
.venv/bin/python scripts/check_connection.py   # can we reach the database?
.venv/bin/python scripts/smoke_tools.py        # do the query helpers work?
.venv/bin/python -m pytest                     # unit tests, no network needed
```

The status badge in the interface reports the same thing: green with a
measurement count when the sensors are readable, red when they are not.

---

## Configuration

A deployment is fully described by two things: its `.env` file and its habitat
profile. No mission-specific value is baked into the source.

### Environment variables

Set in `atlas_backend/.env` (copy from `.env.example`). The essentials:

| Variable | What it does |
| --- | --- |
| `DATA_SOURCE` | Which adapter connects to the habitat: `sqlite` (template default), `grafana`, `influxdb` or `sql`. |
| `HABITAT_CONFIG` | Path to the habitat profile YAML. The template selects the synthetic demo habitat. |
| `GRAFANA_URL` | Grafana adapter: base URL of the habitat Grafana. |
| `GRAFANA_TOKEN` *or* `GRAFANA_USER`/`GRAFANA_PASS` | Grafana adapter: credentials (token wins). |
| `GRAFANA_DATASOURCE_UID` | Grafana adapter: the InfluxDB datasource to query. |
| `INFLUX_URL` | Direct-InfluxDB adapter: base URL of InfluxDB. |
| `INFLUX_TOKEN` *or* `INFLUX_USER`/`INFLUX_PASS` | Direct-InfluxDB adapter: credentials. |
| `INFLUX_DB` | The database name (required for the direct adapter; optional for Grafana). |
| `LLM_PROVIDER` | `ollama` (local, default) or `anthropic` (cloud). |
| `ANTHROPIC_API_KEY` | Only if you want the cloud option. Running locally needs no key. |
| `CORS_ORIGINS` | Browser origins allowed to call the API (the Vite dev server is 5173). |

`.env.example` contains common settings. See [configuration](docs/configuration.md)
for setup details and advanced options. **Never commit `.env`** — it
holds credentials and is git-ignored.

### The habitat profile

Everything about *your* habitat that a database cannot describe about itself
lives in one YAML file: its display name, its room/zone names, which tag keys
name a place, and the units each sensor field carries. See
[Deploying ATLAS for your mission](#deploying-atlas-for-your-mission) for how
to write one; `config/examples/habitat.example.yaml` documents every option.

---

## Connecting a habitat database

### Option A — Grafana proxy (default)

If your telemetry is behind Grafana (the common case), let Grafana hold the
InfluxDB credentials and proxy ATLAS's queries.

```bash
DATA_SOURCE=grafana
GRAFANA_URL=http://<your-grafana-host>
GRAFANA_TOKEN=<service-account-token>     # or GRAFANA_USER / GRAFANA_PASS
GRAFANA_DATASOURCE_UID=<uid>
```

If the datasource uid is wrong, `python scripts/discover_datasources.py` finds
the right one; `python scripts/check_connection.py` confirms the whole path.

### Option B — direct InfluxDB

If you can reach InfluxDB 1.x directly, skip Grafana entirely.

```bash
DATA_SOURCE=influxdb
INFLUX_URL=http://<your-influx-host>:8086
INFLUX_TOKEN=<token>                       # or INFLUX_USER / INFLUX_PASS
INFLUX_DB=<database-name>
```

### Option C — a SQL database (PostgreSQL / MySQL / TimescaleDB)

If your telemetry already lives in a relational database, connect it **without
migrating your data**. You describe your table's columns in the habitat
profile's `sql_mapping` section, and ATLAS maps its model onto them:

```bash
DATA_SOURCE=sql
SQL_DSN=postgresql://user:pass@host:5432/habitat   # or mysql://…, sqlite:///…
HABITAT_CONFIG=config/examples/postgres_habitat.yaml
```

```yaml
# in the habitat profile — point these at YOUR columns
sql_mapping:
  table: sensor_readings
  measurement_column: metric_type     # "temperature", "co2", …
  location_column: room               # optional (the place)
  time_column: ts                     # epoch | datetime | ISO text
  value_column: value
  time_encoding: datetime
```

Install just the driver you need (ATLAS uses the stdlib DB-API, no ORM):
`pip install 'psycopg[binary]'` for PostgreSQL/Timescale, `pip install pymysql`
for MySQL. A full template is
[`config/examples/postgres_habitat.yaml`](atlas_backend/config/examples/postgres_habitat.yaml).

### Option D — SQLite

A local file in the canonical schema — the offline demo, and the simplest path
for a small habitat. See [Try it with zero InfluxDB](#try-it-with-zero-influxdb-the-sqlite-demo).

### Supported data-source adapters

| Adapter | `DATA_SOURCE` | Backend | Status |
| --- | --- | --- | --- |
| Grafana proxy → InfluxDB | `grafana` | InfluxDB 1.x via Grafana | Shipped (reference) |
| InfluxDB 1.x (direct) | `influxdb` | InfluxDB HTTP API | Shipped |
| SQLite | `sqlite` | a local `.db` file | Shipped (also the offline demo) |
| SQL (PostgreSQL / MySQL / TimescaleDB) | `sql` | any relational DB, via a config mapping | Shipped |
| MongoDB / REST / other | *your name* | any store | Via a new adapter — see below |

### Try it with zero InfluxDB (the SQLite demo)

The fastest way to see ATLAS run against a completely different habitat and
database:

```bash
cd atlas_backend
.venv/bin/python scripts/seed_demo_sqlite.py     # builds config/examples/demo_habitat.db
```

Then set these in `.env` and start the backend:

```bash
DATA_SOURCE=sqlite
SQLITE_PATH=config/examples/demo_habitat.db
HABITAT_CONFIG=config/examples/demo_habitat.yaml
```

That habitat — a Greenhouse, Robotics Bay, Medical Bay, Science Lab, Crew
Quarters, a Dormitory and an Airlock, with its own clean and grey water tanks — is
served from a plain SQLite file. Ask it "what's the temperature in the
greenhouse?" or "how much energy did the robotics bay use over 3 days?" and the
answers are queried live, cited, and grounded, exactly as on InfluxDB.

---

## Extending ATLAS

### Writing a new data-source adapter

ATLAS Core talks to a database through a **structured, dialect-neutral
interface**, not through SQL or InfluxQL strings. The telemetry layer builds a
[`Query`](atlas_backend/app/datasource/query.py) object — a measurement, a
field, an aggregate, a time window, a grouping — and your adapter renders it into
*your* database's language. That is why adding PostgreSQL, MySQL, or a REST API
is a self-contained adapter and never a change to core logic.

An adapter implements a handful of methods
([`DataSource`](atlas_backend/app/datasource/base.py)):

```python
from app.datasource.base import DataSource
from app.datasource.query import Query

class MyDataSource(DataSource):
    label = "my backend"

    # --- discovery ---
    def measurements(self) -> list[str]: ...
    def field_keys(self, measurement) -> list[dict]: ...      # [{"field","type"}]
    def tag_keys(self, measurement) -> list[str]: ...
    def tag_values(self, measurement, key) -> list[str]: ...

    # --- the one read path every tool reduces to ---
    def run(self, query: Query) -> dict:
        # translate `query` into your dialect, execute it, and return:
        # {"query": <human text>, "database": ..., "series": [
        #     {"name", "tags": {...}, "columns": ["time", ...], "values": [[...]]}]}
        ...

    def configured(self) -> bool: ...
```

The best worked example is [`sqlite.py`](atlas_backend/app/datasource/sqlite.py):
~200 lines, reads a plain `readings(measurement, location, field, ts, value)`
table, and buckets/aggregates in Python. A SQL adapter (Postgres/Timescale/MySQL)
follows the same shape, translating each `Query` into `SELECT … time_bucket(…) …
GROUP BY …` driven by a table/column mapping in the habitat profile.

Then **register it** in `app/datasource/__init__.py`:

```python
ADAPTERS = {
    "grafana": _make_grafana,
    "influxdb": _make_influxdb,
    "sqlite": _make_sqlite,
    "mybackend": _make_mybackend,   # <- one line
}
```

and **select it** with `DATA_SOURCE=mybackend`, adding whatever connection
settings it needs to `config.py` and `.env.example`. No caller changes.

**Every read path is database-agnostic.** All tools — including the dashboard
charts and the tank-flow reconciliation — ride the structured `run()` path, so
they work on any adapter. What varies is the *tool set*, which is driven by the
habitat profile, not the database: `get_tank_flow` is offered only when the
profile declares `stocks`, and `get_latest_all_phases` only when it
declares an `electrical` meter. A mission with neither is simply never offered
them (the SQLite demo isn't), so the model always has a coherent, applicable set
of tools from configuration alone.

### Other extension points

The backend is organized so each kind of change has one home:

| I want to… | Look in |
| --- | --- |
| Rename a room or dataset for this crew | **Settings → Database nomenclature**, no code, no config |
| Give the assistant a procedure or contact sheet | **Settings → Connectors**, upload a PDF/Word/CSV/text file |
| Add/rename/remove a hand-read meter | **Settings → Database nomenclature**, crew meter log |
| Point at a different database | add an adapter in `app/datasource/` (above) |
| Connect an existing SQL database | `DATA_SOURCE=sql` + a `sql_mapping:` in the profile |
| Configure a new habitat | write a `config/examples/<mission>.yaml` profile |
| Declare this habitat's rooms / units | `zone_names:` / `units:` in the profile |
| Declare tanks or a phased meter (adds those tools) | `stocks:` / `electrical:` in the profile |
| Add a query capability (tool) | `app/telemetry/`, then `app/tools/schemas.py` + `registry.py` |
| Support another model runtime | `app/llm/` — write a `Provider`, list it in `providers.py` |
| Change how ATLAS answers | `app/services/prompt.py` and `app/services/style.py` |
| Add or change a dashboard chart | `app/services/dashboard.py` |

The [backend README](atlas_backend/README.md) has the full map.

---

## Deploying ATLAS for your mission

A new analog mission gets ATLAS running against its own habitat **without
editing any application code** — two files and a run command.

1. **Install** (see [Installation](#installation)).

2. **Write a habitat profile.** Copy the worked example and edit it:

   ```bash
   cd atlas_backend
   mkdir -p config/private
   cp config/examples/habitat.example.yaml config/private/my_mission.yaml
   ```

   The profile holds only what a database can't describe about itself:

   ```yaml
   name: My Mission
   location_tag_keys: [Location, Room]     # tag keys that name a place
   internal_prefixes: [go_, influxdb_]     # DB's own metrics to hide
   zone_names:                             # tag value -> human room name
     Module1: Living Quarters
     Module2: Laboratory
   units:                                  # measurement -> field -> unit
     Temperature: { value: "°C" }
     CO2:         { value: ppm }
   ```

   Everything else (measurement names, fields, tag values) is discovered live —
   leave it out. You can also skip `zone_names` entirely and rename rooms from
   **Settings → Database nomenclature** once ATLAS is running: it lists every
   location and dataset it found in your database and lets you give each one a
   name your crew uses. The database is only ever read.

3. **Point `.env` at your database and profile:**

   ```bash
   DATA_SOURCE=grafana                       # or influxdb
   GRAFANA_URL=...                           # your connection settings
   HABITAT_CONFIG=config/private/my_mission.yaml
   ```

4. **Verify and run:**

   ```bash
   .venv/bin/python scripts/check_connection.py
   .venv/bin/python -m uvicorn app.main:app --reload
   ```

That's the whole port. The mission plan (start date, length, consumption
ceilings) and answer style are set later from the interface and stored in the
database — not in any file you edit.

### Running it for real

The commands above are the development setup (Vite + uvicorn `--reload` on
localhost). For a deployment that outlives a terminal: build the frontend
(`npm run build`) and follow the [authenticated deployment guide](docs/deployment.md).
Serve `dist/` from a real web server, drop `--reload` and
put uvicorn behind a process manager, set `CORS_ORIGINS` to wherever the
frontend is actually served, and terminate TLS in front of it.

---

## What a fresh install looks like

Two things are deliberately empty until you set them:

- **No mission plan.** The Dashboard's Mission view opens on a setup form — a
  start date, a length in days, and the most water and power the mission may
  draw. Until then, ATLAS answers "how are we doing against plan?" by saying no
  plan has been set, rather than comparing against a figure nobody chose.
- **No chat history.** `atlas.db` (SQLite) is created on first boot and is not
  shipped.

The answer style starts on **Concise**; change it on the Settings page.

## The rules ATLAS works under

- **Read-only.** Only `SELECT` and `SHOW`, enforced in code
  ([`app/datasource/wire.py`](atlas_backend/app/datasource/wire.py)), for every
  adapter.
- **Grounding is a design goal, not a guarantee.** Models are instructed to use
  query results; independently check answers against their cited sources. The helpers return an explicit "no data" rather than a value.
- **No invented absence.** ATLAS may not say a sensor doesn't exist unless it
  searched — and it says what it searched.
- **Nothing about the schema is hardcoded.** Measurements, tags, and fields are
  discovered from the database at runtime; only the units and human names live
  in the habitat profile.

---

## Contributing

Contributions are welcome — new adapters, new habitat profiles, new query
capabilities, UI improvements. A good first PR is an adapter for the database
your mission runs, or a habitat profile you can share.

- Keep the data-source seam intact: core code reaches the database only through
  `app.datasource`. If you find yourself importing an adapter by name
  outside `app/datasource/`, that's the smell to avoid.
- Add tests — the suite runs offline (`pytest`), and the parsing/arithmetic
  paths are where quiet bugs hide.
- Run `ruff` (configured in `pyproject.toml`).

## License

Apache License 2.0 — see [LICENSE](LICENSE). ATLAS is meant to be deployed and
reused by any analog mission, and the license is chosen for that: use it, modify
it, ship it, with the patent grant and attribution the license asks for.

Keep credentials and mission data out of every commit. `.env`, the chat-history
database, and anything under `atlas_backend/knowledge/` are gitignored for that
reason — the `.env.example` files are the ones that get committed.
