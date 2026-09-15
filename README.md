# ATLAS

Telemetry, mission budgets, and crew meter logs for analog space habitats.

ATLAS helps a crew answer three questions: **What did we use? Are we on plan?
Where did it go?** Explore water and energy charts, compare daily consumption
with a mission budget, or ask the assistant a question and inspect its sources.

![Water consumption against today, cycle, and mission budgets](docs/images/atlas-mission-plan.png)

Built and maintained by [GianScala](https://github.com/GianScala).
React + TypeScript frontend, FastAPI backend, and local models through Ollama.
Anthropic is available as an optional cloud provider.

## Quick start

You need Python 3.11+ and Node.js 22.12+. Run these commands from the repository
root in two terminals.

**1. Start the backend with synthetic telemetry**

```bash
cd atlas_backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/python scripts/seed_demo_sqlite.py
.venv/bin/python -m uvicorn app.main:app --reload
```

**2. Start the frontend**

```bash
cd atlas_frontend
npm install
npm run dev
```

Open [localhost:5173](http://localhost:5173). The charts work without a language
model. For chat, start [Ollama](https://ollama.com/download), then install and
select a model in **Settings → AI & models**.

The demo contains 30 days of synthetic sensor readings. Mission plans and manual
readings start empty; follow the [consumption guide](docs/consumption-guide.md)
to add them. The seeder preserves an existing database; use `--force` only to
replace that synthetic telemetry with a fresh rolling window.

## How it works

| View | Use it to | Data source |
| --- | --- | --- |
| Habitat consumption | Inspect water use, tank levels, and energy over a selected time range | Habitat telemetry |
| Room analysis | Compare temperature, humidity, CO₂, and power draw across rooms | Room sensors |
| Mission plan | Compare daily use with allowances for today, a three-day cycle, and the whole mission | Telemetry + the crew's saved plan |
| Crew meter log | Break down consumption by room or tap, from morning and evening readings | Manually entered cumulative meter readings |
| Chat | Ask questions and inspect the queries behind the answer | Tools that read telemetry, mission information, and configured context |

### See daily use against your plan

In **Dashboard → Mission plan**, enter the start date, duration, and total water
and energy budgets. ATLAS calculates daily allowances and updates the remaining
allowance as consumption comes in. Add planned extras for activities such as
experiments or cleaning; these reserve part of the existing budget.

The **Day by day** chart shows recorded use, the original allowance, and the
revised allowance for the days ahead. Expand **Every day** for exact numbers.
Missing readings remain gaps; today's consumption is still in progress.

![Exact daily consumption and allowances in the mission table](docs/images/atlas-daily-plan.png)

### Turn manual readings into consumption

Open **Crew meter log** from Habitat consumption, choose power or water, then
expand **The sheet**. Enter the number on each dial, not the amount used.
ATLAS subtracts successive readings to calculate daytime and overnight use.

For example, power readings of **100 → 112 → 117 kWh** mean **12 kWh daytime**,
**5 kWh overnight**, and **17 kWh for the full day**. The third reading is the
following morning. Without it, the overnight interval is still open.

![Manual dial readings alongside calculated daytime and overnight consumption](docs/images/atlas-manual-readings.png)

The log shows daily totals and shares by room or tap. Its comparison with
telemetry helps you investigate differences. Manual readings are kept separate:
they do not fill telemetry gaps or change the consumption shown in Mission plan.

![Crew meter log showing how recorded energy use is distributed](docs/images/atlas-crew-log.png)

See the [step-by-step consumption guide](docs/consumption-guide.md) for units,
incomplete rounds, and interpreting the comparison. All consumption screenshots
use an isolated synthetic demo; figures vary with the capture date.

## Connect your habitat

ATLAS reads through a data-source adapter. A YAML habitat profile supplies room
names, units, tanks, mission resources, and crew meters.

### Supported data-source adapters

| Adapter | `DATA_SOURCE` | Configuration |
| --- | --- | --- |
| SQLite (default) | `sqlite` | `SQLITE_PATH` to an ATLAS readings database |
| PostgreSQL / MySQL / TimescaleDB | `sql` | `SQL_DSN`, a driver, and `sql_mapping` in the profile |
| InfluxDB 1.x | `influxdb` | `INFLUX_URL`, `INFLUX_DB`, and credentials |
| InfluxDB through Grafana | `grafana` | `GRAFANA_URL`, credentials, and `GRAFANA_DATASOURCE_UID` |

Copy a [profile example](atlas_backend/config/examples) into
`atlas_backend/config/private/`, then set `HABITAT_CONFIG` and the adapter's
connection settings in `.env`. Use read-only database credentials.
See [configuration](docs/configuration.md) for details.

## Development

```text
atlas_backend/app/
  datasource/   Database adapters and the structured Query interface
  telemetry/    Sensor queries and consumption calculations
  mission/      Plans, daily tracking, and manual meter logs
  tools/        Tools available to the assistant
  services/     Agent loop, dashboard, settings, and supporting services
  api/          FastAPI routes
atlas_frontend/src/
  pages/        Chat, dashboard, mission, meter log, and settings
  hooks/        Fetching, caching, and streamed chat state
  lib/          API contracts, formatting, and chart helpers
  components/   Shared controls and charts
```

Read the [backend README](atlas_backend/README.md) or
[frontend README](atlas_frontend/README.md) for commands and implementation notes.

### Writing a new data-source adapter

Implement [DataSource](atlas_backend/app/datasource/base.py), render the
structured [Query](atlas_backend/app/datasource/query.py) for your database,
and register the adapter in `app/datasource/__init__.py`. Use the SQLite adapter
as an example. Keep database-specific code inside `datasource/` and add tests
for discovery, filtering, time grouping, and aggregation.

For a new tool, add the telemetry function and register it under `app/tools/`.
For a chart, update the dashboard catalogue or habitat profile. See
[CONTRIBUTING.md](CONTRIBUTING.md) for checks and contribution guidelines.

## Deployment and limits

ATLAS is a shared application for a trusted crew. Remote deployments need
authentication in front of the whole site; follow the
[deployment guide](docs/deployment.md). Keep private mission data and credentials
out of this repository.

The assistant is instructed to cite sources and avoid unsupported figures, but
model answers can still be wrong. Check the readings behind operational decisions.
Cloud inference sends questions and retrieved context to the selected provider.
See [security and privacy](SECURITY.md) and [release status](docs/release-readiness.md).

## Documentation

- [Consumption guide](docs/consumption-guide.md) — plans, daily totals, and manual readings
- [Configuration](docs/configuration.md) — telemetry, profiles, models, and environment variables
- [Backend](atlas_backend/README.md) · [Frontend](atlas_frontend/README.md) — developer setup and architecture
- [Screenshot setup](docs/screenshots.md) — reproduce the synthetic examples

## License

[Apache License 2.0](LICENSE). See [NOTICE](NOTICE) and
[third-party notices](THIRD_PARTY_NOTICES.md) for attribution.
