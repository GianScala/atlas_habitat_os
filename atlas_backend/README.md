# ATLAS - backend

A FastAPI service that answers natural-language questions about habitat
telemetry, using only data it queries while you wait.

Telemetry lives in the habitat's own database.
ATLAS reaches it through a **data-source adapter** chosen by `DATA_SOURCE`:
`grafana` proxies queries through Grafana (the default - Grafana holds the
InfluxDB credentials, so no InfluxDB token is needed), and `influxdb` connects
to InfluxDB directly. Grafana is one adapter, not a core dependency; see
[`app/datasource/`](app/datasource) and the root
[README](../README.md#extending-atlas) for writing another.

What the habitat *is* - its display name, room names, tag conventions, and
sensor units - is a **habitat profile** (`config/examples/habitat.example.yaml`),
selected by `HABITAT_CONFIG`, not code.

The model runs **on this machine** by default, under Ollama. See
[Which model answers](#which-model-answers).

## Ground rules

These are enforced in code, not just documented.

- **Read-only.** Only `SELECT` and `SHOW`. Identifiers that aren't plain
  alphanumeric are refused outright rather than escaped.
- **No invented numbers.** A number appears in an answer only if a query in
  that turn returned it. Helpers return `data: null` rather than a value, so
  there is nothing to fabricate from.
- **No invented absence.** ATLAS may not say a sensor "doesn't exist" unless a
  discovery call that turn came back without it - and must say what it
  searched. This is the more dangerous error in a habitat: "we have no sensor
  for that" is a claim someone might act on.
- **Nothing about the schema is hardcoded.** Measurements, tag keys, tag
  values, and fields are discovered at runtime. Units are the sole exception -
  InfluxDB stores none - and an unverified unit is reported as unknown rather
  than guessed.
- **Every answer cites itself.** Measurement, location, timestamp, plus the
  exact InfluxQL that ran.

## Layout

Each layer depends only on the ones beneath it.

```
app/
├── main.py            application factory, CORS, error handling
├── config.py          all configuration, read once from the environment
├── datasource/
│   ├── base.py        the DataSource interface - ATLAS Core's one seam to a DB
│   ├── wire.py        shared InfluxDB read-only enforcement + response parsing
│   ├── grafana.py     Grafana-proxy adapter (the reference/default)
│   ├── influxdb.py    direct InfluxDB 1.x adapter
│   └── __init__.py    the registry: influxql() + get_data_source()
├── habitat/           the habitat profile loader (name, zones, units)
├── api/
│   ├── deps.py        shared dependencies (provider, agent, repository)
│   └── routes/        health · chat · conversations · dashboard · mission · models · metadata
├── llm/
│   ├── base.py        what a provider is: a thread in, a streamed turn out
│   ├── ollama_provider.py    a model running on this machine
│   ├── anthropic_provider.py Claude, over the cloud API
│   ├── ollama_client.py      HTTP to the local daemon
│   ├── translate.py   our stored history <-> Ollama's chat format
│   ├── catalogue.py   the models offered on the Models page
│   ├── inventory.py   what is installed, and what it can really do
│   ├── selection.py   which provider and model are in force
│   └── providers.py   building the one in force
├── mission/
│   ├── plan.py        the mission, the ceilings, the extras, and validation
│   ├── dayplan.py     THE ALGORITHM: a ceiling in, an allowance per day out
│   ├── meters.py      which instrument answers "how much did we use"
│   ├── periods.py     when today, this cycle, and the mission begin
│   ├── repository.py  the crew's own plan, on disk
│   ├── tracking.py    used against planned, and the verdict
│   ├── brief.py       the plan as a section of the system prompt
│   └── query.py       the plan as a tool result, for get_mission_plan
├── services/
│   ├── agent.py       the streaming agent loop
│   ├── prompt.py      the system prompt
│   ├── style.py       the register answers are written in
│   ├── transcript.py  stored messages -> a readable transcript
│   ├── dashboard.py   the chart panel catalogue
│   └── sse.py         server-sent event framing
├── storage/
│   ├── database.py    SQLite connections and schema
│   └── conversation_repository.py   all the SQL lives here
├── tools/
│   ├── schemas.py     tool definitions as the model sees them
│   └── registry.py    name -> telemetry function
├── telemetry/         builds InfluxQL, parses series; no transport knowledge
│   ├── influxql.py    query-string construction; no schema knowledge
│   ├── units.py       units, from the habitat profile (not discoverable)
│   ├── zones.py       human names for tag values, from the habitat profile
│   ├── discovery.py   the database describing itself, cached
│   ├── filters.py     question terms -> WHERE clauses
│   ├── readings.py    point-in-time values, short-term history
│   ├── aggregation.py statistics and consumption over long windows
│   ├── timeseries.py  bucketed multi-series queries, for charting
│   └── availability.py what is live now, as opposed to what exists
├── schemas/           request, response, and event contracts
└── core/              errors and logging
```

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/python scripts/seed_demo_sqlite.py
```

The template selects the synthetic SQLite demo; the seed command creates its
ignored telemetry database. To connect your own habitat, change `DATA_SOURCE`,
its connection settings and `HABITAT_CONFIG`. See
[configuration](../docs/configuration.md) for adapters and advanced options.
`ANTHROPIC_API_KEY` is needed only for cloud inference.

Install [Ollama](https://ollama.com/download) and start it (`ollama serve`, or
open the app). Models are installed from the Models page in the interface.

### Optional offline voice

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

## Running

```bash
.venv/bin/python -m uvicorn app.main:app --reload
```

Serves on `http://127.0.0.1:8000`. Interactive API docs at `/docs`.

## Checking it works

**The connection**

```bash
.venv/bin/python scripts/check_connection.py
```

Passes when the last line reads `OK`. A large measurement count is expected:
habitat sensors plus InfluxDB's own internal metrics (`go_*`, `storage_*`,
`task_*`), which ATLAS filters out.

**The query helpers**

```bash
.venv/bin/python scripts/smoke_tools.py
```

Discovers the schema live, prints readings with timestamps, then demonstrates
both aggregation modes. `-> no data` is a valid result, not a failure.

**The unit tests** (no network needed)

```bash
.venv/bin/python -m pytest
```

## API

| Method   | Path                       | Purpose                                   |
| -------- | -------------------------- | ----------------------------------------- |
| `POST`   | `/api/chat`                | Ask a question. Streams SSE events. Pass `conversation_id` to continue a thread. |
| `GET`    | `/api/conversations`       | Every stored thread, newest activity first. |
| `GET`    | `/api/conversations/{id}`  | One thread, projected into a readable transcript. |
| `DELETE` | `/api/conversations/{id}`  | Forget one thread.                        |
| `DELETE` | `/api/conversations`       | Forget every thread.                      |
| `GET`    | `/api/dashboard`           | Every chart panel for a `range`.          |
| `GET`    | `/api/dashboard/ranges`    | The selectable windows.                   |
| `GET`    | `/api/mission/plan`        | The mission as declared, its ceilings, and its extras. |
| `PUT`    | `/api/mission/plan`        | Declare or change it. Anything omitted keeps its value. |
| `POST`   | `/api/mission/plan/reset`  | Forget the mission, every ceiling, and every extra. |
| `POST`   | `/api/mission/extras`      | Book an extra onto a mission day, or onto all of them. |
| `PUT`    | `/api/mission/extras/{id}` | Change one extra.                         |
| `DELETE` | `/api/mission/extras/{id}` | Drop one; its amount returns to the other days. |
| `GET`    | `/api/mission/tracking`    | The day plan, what was drawn against it, and what the days ahead now allow. |
| `GET`    | `/api/settings/assistant`  | The register answers are written in, and the ones on offer. |
| `PUT`    | `/api/settings/assistant`  | Change it. Applies from the next question.|
| `GET`    | `/api/models`              | What is installed, what is offered, and which model answers. |
| `POST`   | `/api/models/active`       | Use this provider and model from now on.  |
| `POST`   | `/api/models/install`      | Download a model. Streams pull progress as SSE. |
| `POST`   | `/api/models/remove`       | Delete a model from disk.                 |
| `GET`    | `/api/health`              | Configured and running? No network calls. |
| `GET`    | `/api/health/datasource`   | Can we reach the database, and is a model ready? |
| `GET`    | `/api/meta/measurements`   | What the habitat monitors, discovered live. |
| `GET`    | `/api/meta/zones`          | Tag value -> human name.                  |
| `GET`    | `/api/meta/suggestions`    | Starter questions for the empty screen.   |
| `POST`   | `/api/meta/refresh`        | Re-read the schema without a restart.     |
| `GET`    | `/api/voice/status`        | Check local transcription and speech readiness. |
| `PUT`    | `/api/voice/settings`      | Save an installed voice and dictation language. |
| `POST`   | `/api/voice/transcribe`    | Transcribe an uploaded browser recording locally. |
| `POST`   | `/api/voice/synthesize`    | Render answer text to a local WAV response. |

## Which model answers

Two providers, one interface. `app/llm/base.py` defines it: hand over the
thread and the tools, get a streamed turn back. The agent loop does not know
which one it is driving.

| Provider | Where it runs | What leaves the machine |
| --- | --- | --- |
| `ollama` | here, on this machine | nothing |
| `anthropic` | Anthropic's data centre | the question, the history, and every reading pulled back |

The choice is stored in `app_settings` and set from the Models page; the
`LLM_PROVIDER` and `OLLAMA_MODEL` values in `.env` are only the fallback for a
system where nobody has chosen yet. The model is remembered **per provider**,
so trying the cloud once and switching back does not lose the local choice.

**One stored format.** History is kept as Anthropic content blocks - text,
thinking, `tool_use`, `tool_result` - whichever model produced it, so a thread
started under one model can be continued under another. `llm/translate.py`
converts to and from Ollama's flatter format on the way past. Two asymmetries
live there and nowhere else:

- **Ids.** Anthropic gives every tool call an id and matches results to it;
  Ollama matches by position and name. Ids are minted on the way in, because
  the pairing repair in `conversation_repository` depends on them, and
  resolved back to names on the way out.
- **Reasoning is not sent back.** Anthropic requires its signed thinking block
  returned verbatim; Ollama's models are trained on threads where only the
  conclusion survives. So thinking is stored and displayed but dropped from
  what goes back to a local model.

**Tool support is the thing to check.** ATLAS answers by querying InfluxDB,
so a model that cannot call a tool cannot read a sensor - and will write a
fluent, confident, entirely invented answer instead. The catalogue in
`llm/catalogue.py` carries an expectation per model; once a model is on disk,
Ollama reports what the weights can really do and that measurement replaces
the guess. The Models page says which of the two it is showing.

**Reasoning arrives two ways.** Models that declare the capability put it in a
`thinking` field. Others write `<think>…</think>` into the content and leave
the reader to sort it out - including across chunk boundaries, so `<thi` can
end one chunk and `nk>` start the next. `ThinkStream` in `ollama_provider.py`
handles both, and the interface never learns which kind it is talking to.

Asking a model that cannot think to think is an error rather than a no-op, so
the first request asks and a refusal is retried without it. The daemon knows
better than a hardcoded list would.

## Chat history

Threads are stored in SQLite (`atlas.db` by default) and survive restarts.
The stored form is exactly what the Messages API needs back - user strings,
assistant content blocks, `tool_result` blocks - so a reopened thread replays
to the model verbatim.

That is not what a person reads, so `services/transcript.py` projects it into
the same shape the live event stream produces: text, the queries behind it,
and their outcomes. **Nothing is stored twice**, which is what stops the two
views drifting apart.

The whole thread stays on disk; `MAX_TURNS_PER_CONVERSATION` bounds only how
much of its tail is replayed to the model on each request. The window always
opens on a real question - note that a `tool_result` batch also rides on a
`user` message, so checking the role alone would let a window start on an
orphaned result the model cannot match to its call.

## Dashboard

`services/dashboard.py` holds the panel catalogue: which measurement, which
field, which rooms, and how to aggregate. The browser asks for a range and
gets back panels it can draw without knowing anything about the habitat.

Three aggregation modes, because the habitat has three kinds of number:

| Mode | For | Meaning |
| --- | --- | --- |
| `mean` | a level or rate | average within each bucket |
| `delta` | a cumulative meter, or a tank level | net change, signed |
| `drawdown` | consumption from a supply tank | how far the level fell; a refill counts as zero use, not negative use |

Panels are curated on purpose. The assistant must never assume what exists -
a wrong "there is no sensor for that" is a claim someone might act on - but a
dashboard is a view someone chose, so naming rooms and excluding rollups is
appropriate here in a way it would not be in `telemetry/`.

A series is keyed by the **room**, not by the tag that names it. `Temperature`
calls the dormitory `Container3` and `Energy` calls it `Dormitory`; keying on
the raw tag would make one room look like two and give it a different colour
on every chart. Where two tag values genuinely hold separate data for one
place (`AirLock` and `Airlock`), both are shown under their raw tags rather
than averaged together.

One panel failing is reported on that panel - a broken sensor leaves a gap,
not an error screen.

## Mission plan

Everything else here reports what the habitat did. `app/mission/` is the only
part holding a number nobody measured - an intention - and putting the two
side by side. It is its own package for that reason: a budget is a decision,
with different provenance and different ways of being wrong than a reading.

The crew declares **three facts** - a start date, a length in days, and the
most of each resource the mission may draw end to end - and `dayplan.py`
derives everything else. Nothing derived is ever stored: a stored derivation is
a figure that will eventually disagree with what it was derived from, and the
disagreement will be silent.

```
extras_total = every extra, summed over the days it lands on
flat         = (ceiling - extras_total) / mission days
planned[d]   = flat + extras on d
```

**`sum(planned) == ceiling`, exactly.** That identity is why the plan is
computed this way rather than day by day, and it is asserted from several
directions in `tests/test_mission.py`. Every window below is a sum over the
same array, so the three cards can disagree with each other only if the
arithmetic is wrong - not because someone set three figures that never
reconciled, which is what the previous design allowed.

**Extras are carved OUT of the ceiling, not added to it.** A crew that books a
300-litre experiment has not been granted 300 more litres; it has decided where
300 of its litres go, and every other day drops accordingly. A ceiling that
grew each time someone remembered an experiment would not be a ceiling.

**Then it re-plans, on every read:**

```
revised[d] = (ceiling - consumed - extras still to come) / days still to come
             + extras on d
```

This is what makes the page a planning tool rather than a scoreboard. A crew
three days over on water does not want to be told it is over; it wants to know
what a day looks like from here if the mission is still to close on budget.
Today counts as a day still to come - it is running, its allowance is not spent,
and dropping it from the divisor would hand the whole of today's overspend to
tomorrow. Where the extras still booked cost more than what is left, no flat
rate closes the mission: `feasible` goes false, the shortfall is stated, and the
flat part is floored at zero rather than published as a negative allowance
nobody can act on.

Three windows, all sums over that one array:

| Horizon | Runs from | Covers |
| --- | --- | --- |
| `day` | local midnight | today |
| `cycle` | a three-day block counted from MD-01 | e.g. MD-13 to MD-15 |
| `mission` | MD-01 | the whole declared run |

**Provenance is a row, not a flag.** A row in `mission_totals` is a figure the
crew set; its absence means nobody has. There is no third state to get out of
step, resetting the plan is deleting rows, and every figure derived from a
shipped default is labelled as one all the way to the screen. The figures in
`app/mission/default_plan.json` are never a plan - they only pre-fill the setup
form, visibly, in a box the crew overwrites before saving.

**The day boundary is the crew's, not UTC's.** The plan carries an offset from
UTC in whole hours - whole, because consumption is attributed to hourly buckets
at best, and a boundary inside an hour would split that hour's use across two
days with no way to say how much belonged to each. `influxql.time_group()` and
`tanks._period_start()` both take it, so a period means the same thing whether
it was bucketed in the query or folded in Python.

**One query per resource.** Every window and the day-by-day chart come from the
same per-local-day breakdown, so today's figure is a term in the mission's by
construction. A query per horizon would have let three cards disagree about the
same afternoon, since each would apply the water deadband over a different
window.

**A verdict needs both figures.** "80% of the plan" is alarming at breakfast and
a good day at midnight, so every window carries the share spent AND
`planned_by_now` - what the plan itself expected by this moment, with finished
days in full, today at the share of it that has passed, and each extra on its
own day. That last part matters: a 200-litre experiment booked for the last day
of a cycle is not two-thirds spent on the second day, and pacing against it as
though it were would report a crew comfortably ahead right up until it wasn't.
Below `periods.PACE_FLOOR` of a window elapsed no projection is published at
all - four minutes into a day, one draw of the tank extrapolates to a
fortnight's water.

Nothing is estimated. A day the sensors did not cover has no figure, is counted
in `days_uncovered`, and is never read as a day of zero - so `consumed` is
stated as the floor it is, and the allowance ahead is the most optimistic one
still consistent with the record.

### The plan and the model

The plan is the one thing on this system that no sensor knows, so it reaches the
model two ways, deliberately split:

- **`brief.py`** writes it into the system prompt every turn - small, from
  SQLite, and the context every consumption question is really asking about. It
  carries **no consumption figures at all**: a used figure in a system prompt is
  a number the model did not query, written once and stale ever after, which is
  the exact failure every other rule here exists to prevent.
- **`query.py`** backs the `get_mission_plan` tool, which returns the plan *and*
  what the meters recorded against it. Live figures arrive the way every other
  figure does - through a tool, in the turn that uses them. It is the same
  `build_tracking` the interface draws, so a crew that asks ATLAS and then opens
  the Mission view cannot be given two different answers.

With no mission declared, both say so plainly and instruct the model to refuse
to compare consumption against a target nobody set.

### Answer styles

`services/style.py` holds four registers - concise, detailed, unhinged, and the
crew's own text - appended to the prompt **after** the grounding rules, each
restating that those rules outrank it. A style that quietly loosened them would
be the most dangerous thing in this repository: an assistant that is funnier and
occasionally invents a number is worse than no assistant, because a crew would
take longer to notice. Custom text is wrapped and quoted as a preference rather
than pasted in as new instructions, on the same reasoning that tool results are
handed over as data.

### Chat events

`POST /api/chat` returns `text/event-stream`. One JSON object per `data:` line:

| `type`           | Carries                                        |
| ---------------- | ---------------------------------------------- |
| `start`          | `conversation_id` - keep it for follow-ups - and which model is about to answer |
| `thinking_delta` | summarised reasoning, token by token           |
| `text_delta`     | the answer, token by token                     |
| `tool_call`      | a query the model decided to run               |
| `tool_result`    | whether it succeeded and returned data         |
| `sources`        | the InfluxQL behind the answer                 |
| `error`          | a plain reason, plus a `kind` for the interface |
| `done`           | the turn is finished                           |

The models live in `app/schemas/chat.py`; the frontend mirrors them in
`src/lib/types.ts`. **Keep the two in step.**

## Which aggregation tool for which question

Picking the wrong one gives a meaningless number, so the tool descriptions say
so explicitly and the code checks its own assumption.

Every field is one of three things, and each has exactly one tool that means
anything on it.

| Question shape                                        | Tool              | Why |
| ----------------------------------------------------- | ----------------- | --- |
| "average temperature this week", "average power draw" | `summarize`       | A rate or level at an instant - mean, min, max, count per period |
| "how many kWh did we use"                             | `get_consumption` | A cumulative totaliser - usage is last − first |
| "how much water did we use", "how much grey water"    | `get_tank_flow`   | A stock that rises and falls - how far the level fell and how far it rose, separately |

`get_consumption` returns both endpoints for every period alongside each delta,
so the arithmetic is checkable, and it **verifies its own assumption**: if the
field ever drops - or dips and recovers inside a bucket, which endpoint
arithmetic alone cannot see - it returns `cumulative: false` with a warning and
a `redirect` to `get_tank_flow`. All arithmetic happens in Python over values
the database returned - the model never computes totals itself.

### Why a tank needs its own tool

A water tank is not a totaliser and not a rate. It moves in two directions for
two unrelated physical reasons, and netting them destroys both. Over three days
the clean tank rose 774 L on a delivery and fell 447 L into the habitat; its net
change was +327 L - a number that is correct, is not consumption, is not refill,
and answers nothing. `get_tank_flow` therefore never nets. It reports `fell` and
`rose` separately and leaves the naming to the caller: on a **supply** tank the
fall is consumption and the rise is a delivery, on a **waste** tank the rise is
what was produced and the fall is a service emptying.

Two hazards are handled in the tool rather than left to the model:

- **Noise.** Differencing amplifies it and one-sided accounting rectifies it, so
  a motionless tank would report use forever. Raw one-minute samples over three
  days give 1402 L of "consumption" on a tank that actually used 447. Beaten by
  averaging into analysis buckets and then by a deadband held against a
  reference level. The floors live in `telemetry/instruments.py` with their
  derivation, and the dashboard reads the same table so a chart and an answer
  from one gauge cannot disagree. That reference is seeded from several buckets
  rather than one: seeded from a single raw sample it carried the gauge's own
  dither into every bar downstream, and two ranges of the dashboard reported
  the same minute as 2.5 L and 2.8 L.
- **The unconfirmed edge.** A glitch is recognised by having sound readings
  either side of it, which the newest bucket does not yet have. Charged
  regardless, a live dashboard bills every edge glitch in full - one bucket
  read 17.4 L of use against the 4.2 L that had really gone. So the newest
  bucket is held back until the next one confirms it. Nothing is lost, only
  delayed: the reference does not move while it waits.
- **Clipping.** Each analysis bucket is a mean, so buckets coarser than the
  events inside them pull the peaks inward. At three-hour resolution an 800 L
  delivery reports as 439 L. See `influxql.resolution_minutes`.

The reconciliation is always returned - `fell`, `rose`, the net they imply, the
net the opening and closing levels imply, and the bounded gap between them - so
the figure is checkable rather than merely plausible.

Per-period averages divide by the **length of the window requested**, not by the
number of calendar buckets it touches. A rolling three-day window that starts
mid-morning touches four UTC-midnight days, and dividing by four understates
every daily figure by a quarter while looking entirely reasonable.

Consumption is also computed **per series**. Three electrical phases each keep
their own totaliser; a `first()`/`last()` across the merged set subtracts one
meter's reading from another's, producing a large, entirely fictional number
that still looks monotonic. Series tagged as already-aggregated (`Phase=Total`)
are excluded from the sum and reported separately as a cross-check.

## Habitat zones

The database tags locations by container ID; ATLAS translates.

| Tag          | Zone       |     | Tag          | Zone             |
| ------------ | ---------- | --- | ------------ | ---------------- |
| `Atrium`     | Atrium     |     | `Container6` | Analytic Lab     |
| `Container1` | BioLab     |     | `Container7` | Water Storage    |
| `Container2` | Operations |     | `AirLock`    | AirLock          |
| `Container3` | Dormitory  |     | `EVAarea`    | EVA area         |
| `Container4` | Kitchen    |     | `Environment`| External weather |

Others exist that aren't in this table (`SWAMP`, `Aquarium1`, `LEO_ROVER`,
`EVA_1..3`); `describe()` reports the real set, and ATLAS can query them by tag
name - it just can't translate a nickname it hasn't been told. This table is
**configuration**: it lives in the habitat profile
(its `zone_names:` section) or renamed live on the Naming page, so change them there,
not in code. A different mission ships its own profile.

**`AirLock` and `Airlock` are separate tags holding separate data.** Asking for
either covers both, and the answer reports `matched_tag_values` so you know.

`Electricity` is tagged by `Connection`/`Phase`, not `Location`, and has 11
fields including the `totalForward*Energy` counters used for consumption.

## Learning the habitat's conventions

Dashboards encode which datasource holds what, the exact InfluxQL each panel
runs, and the unit it renders in - which InfluxDB itself does not store.

```bash
.venv/bin/python scripts/inspect_dashboards.py
.venv/bin/python scripts/inspect_dashboards.py water
```

Ends with a paste-ready unit block for the habitat profile's `units:` section
(its `units:` section).

## Troubleshooting

| What you see | What it means |
| --- | --- |
| `Could not reach Ollama at …` | The daemon is not running. `ollama serve`, or open the app. |
| `The model … is not installed` | Install it from the Models page, or pick one already on disk. |
| An answer with numbers but no queries behind it | The selected model cannot call tools. The Models page says which can; change it. |
| The first question of a session takes half a minute | The weights are being read off disk. `OLLAMA_KEEP_ALIVE` decides how long they stay loaded. |
| A local model forgets what it was told earlier in the thread | `OLLAMA_NUM_CTX` is too small for the prompt plus the tools plus the history. |
| `HTTP 401 Unauthorized` | Grafana rejected the credentials. |
| `HTTP 403 Forbidden` | Valid but under-privileged; ATLAS falls back to a viewer-readable endpoint automatically. |
| `Cannot reach Grafana` | Not on the habitat network. |
| `No datasource with uid ...` | Run `scripts/discover_datasources.py`. |
| "I didn't find a measurement for X" | Believe it only as far as it goes - it lists what it searched. Run `inspect_dashboards.py X` to see whether a dashboard reads it from a *different* datasource. |
| A unit is missing from an answer | Expected. Run `inspect_dashboards.py` and paste its unit block into the habitat profile's `units:`. |

## Choosing a data source

The backend reaches the database through a **structured, dialect-neutral
interface** in [`app/datasource/`](app/datasource): the telemetry layer builds a
`Query`, and the active adapter (chosen by `DATA_SOURCE`) renders it into its own
language.

- **`grafana`** (default) - queries proxied through Grafana; no InfluxDB token
  needed. Set `GRAFANA_URL`, credentials, and `GRAFANA_DATASOURCE_UID`.
- **`influxdb`** - a direct connection to InfluxDB 1.x's `/query` endpoint. Set
  `INFLUX_URL`, a token (or user/pass), and `INFLUX_DB`.
- **`sqlite`** - a local SQLite file in the canonical `readings` schema, which
  speaks no InfluxQL at all. It's the offline demo and the proof the interface
  is database-agnostic: `python scripts/seed_demo_sqlite.py`, then
  `DATA_SOURCE=sqlite`, `SQLITE_PATH=…`, `HABITAT_CONFIG=…`.

Nothing above `app/datasource/` changes between them. Writing an adapter for
another database (MongoDB, REST) is documented in the root
[README](../README.md#writing-a-new-data-source-adapter). Every read path -
including the dashboard charts and tank-flow - runs through the structured
`Query`, so all of it works on every adapter; which *tools* are offered is
driven by the habitat profile (`stocks`, `electrical`), not the
backend. (`scripts/inspect_dashboards.py` and `discover_datasources.py` are
Grafana-only and simply don't apply to the other adapters.)

## Known limitations

- **Only the configured datasource is queried.** `influxdb-2-IQL-EVA` (uid
  `advjon4p9wetca`, database `EVA`) holds its own `Temperature`/`Humidity`.
  `influxql()` accepts a `uid=` override, so wiring it in is small - run
  `inspect_dashboards.py` first to see which panels read from it.
- Several datasources in this Grafana are broken independently of ATLAS:
  `influxdb` and `influxdb-2-srv2` fail auth, `influxdb-1` has no URL,
  `influxdb-KOTA` 502s.
- Consumption periods align to UTC midnight unless a caller passes
  `offset_minutes`, so the first and last may be partial; `average_per_period`
  includes them. The mission plan passes its own boundary; the chat tools do
  not, and answer in UTC days.
- A stored thread does not record which model wrote each turn, so a reopened
  conversation shows the model in force now rather than the one that answered
  at the time. Only the live stream carries per-turn attribution.
- The schema is cached for the life of the process. `POST /api/meta/refresh`
  re-reads it after a sensor is added.
