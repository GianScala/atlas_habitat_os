# Configuration

Copy `atlas_backend/.env.example` to `atlas_backend/.env`. The template contains
common settings; omitted options use the defaults in
[`Settings`](../atlas_backend/app/config.py). Set real credentials only in the
ignored `.env` file. Do not replace an optional default with an empty value:
empty strings override string defaults.

## Start with the synthetic demo

After installing backend requirements, run from `atlas_backend`:

```sh
cp .env.example .env
.venv/bin/python scripts/seed_demo_sqlite.py
.venv/bin/python -m uvicorn app.main:app --reload
```

The template selects SQLite and `config/examples/demo_habitat.yaml`. The seed
command creates `config/examples/demo_habitat.db`; the database is not shipped
or generated automatically at startup. Start Ollama and install a model from
the Models page for chat. Telemetry views do not require a language model.

## Use your own telemetry

Change `DATA_SOURCE` and configure only the selected adapter:

| Source | Required configuration |
| --- | --- |
| `sqlite` | `SQLITE_PATH` pointing to an ATLAS readings database |
| `grafana` | `GRAFANA_URL`, `GRAFANA_DATASOURCE_UID`, and a token or user/password |
| `influxdb` | `INFLUX_URL`, `INFLUX_DB`, and credentials when required by the server |
| `sql` | `SQL_DSN`, a database driver, and `sql_mapping` in the habitat profile |

Use read-only credentials. Store your habitat profile in `config/private/` and
set `HABITAT_CONFIG` to its path. See the root README's
[data-source examples](../README.md#supported-data-source-adapters) and
[deployment guide](deployment.md) for remote hosting.

`DATABASE_PATH` stores ATLAS conversations and settings; `SQLITE_PATH` points to
telemetry. These are separate databases. `KNOWLEDGE_DIR` stores uploaded files.
Relative paths for these settings and `HABITAT_CONFIG` resolve from the backend
directory. Mission plans and UI preferences are stored in the application
database, not the env file. Model choices saved in the UI override provider/model
fallbacks from the environment.

## Models and optional voice

Local inference uses Ollama. Select `LLM_PROVIDER=anthropic` and provide
`ANTHROPIC_API_KEY` to use the cloud provider. Leave `ANTHROPIC_MODEL` omitted
for the application default, or set an available model ID. Cloud inference sends
questions and retrieved context to that provider; see [security](../SECURITY.md).

Voice is optional. Its model files are downloaded separately and remain ignored.
See [local voice setup](../atlas_backend/README.md) for tools and model details.

## Advanced settings

These need not be copied into `.env` unless you want to override them. Defaults
and validation rules are defined in [`app/config.py`](../atlas_backend/app/config.py).

| Area | Additional variables |
| --- | --- |
| Database calls | `DATASOURCE_TIMEOUT` |
| Knowledge search | `KNOWLEDGE_RESULTS` |
| Ollama tuning | `OLLAMA_NUM_CTX`, `OLLAMA_MAX_TOKENS`, `OLLAMA_TEMPERATURE`, `OLLAMA_KEEP_ALIVE`, `OLLAMA_TIMEOUT`, `OLLAMA_THINKING` |
| Model storage display | `OLLAMA_MODELS_DIR` (display only; Ollama manages its own storage) |
| Anthropic tuning | `ANTHROPIC_MAX_TOKENS`, `ANTHROPIC_EFFORT`, `ANTHROPIC_THINKING` |
| Agent/history | `MAX_TOOL_ROUNDS`, `MAX_TURNS_PER_CONVERSATION`, `MAX_CONVERSATIONS_LISTED` |
| Voice tools | `VOICE_WHISPER_CLI`, `VOICE_FFMPEG_CLI`, `VOICE_PIPER_CLI` |
| Voice tuning | `VOICE_WHISPER_LANGUAGE`, `VOICE_WHISPER_THREADS`, `VOICE_MAX_UPLOAD_MB`, `VOICE_TIMEOUT` |

Increasing the Ollama context window increases memory use. Measure on your target
machine; the prompt, tools, conversation history and output all need capacity.

## Frontend

No env file is required for local development. If needed, copy
`atlas_frontend/.env.example` to `.env.local` in that directory.
`VITE_API_BASE_URL` is empty by default so requests use `/api` on the same origin.
A separate API origin must be configured before building, with matching backend
CORS settings and an appropriate authentication setup. All `VITE_*` values used
by frontend code are public; never use them for API keys or passwords.

The development/preview proxy target is read from the shell, not `.env.local`:

```sh
VITE_API_TARGET=http://127.0.0.1:8001 npm run dev
```

Production hosting should follow [the authenticated deployment guide](deployment.md).
