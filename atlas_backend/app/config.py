"""Runtime configuration, read once from the environment.

Every tunable lives here. Nothing else in the backend calls os.getenv, so a
deployment is fully described by its .env file and this module.
"""

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration, validated at startup."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Data source: which adapter connects ATLAS to the habitat ---------

    # sqlite   read a local SQLite file in ATLAS's canonical readings schema.
    # sql      map onto an existing SQL database (Postgres/MySQL/Timescale/...).
    # influxdb talk to InfluxDB 1.x directly over its HTTP query API.
    # grafana  reach a habitat InfluxDB through Grafana's proxy.
    #
    # No adapter is privileged. The default is sqlite because it is the only one
    # that can work with nothing configured: an unset DATA_SOURCE lands on the
    # bundled demo rather than on a network adapter with no host to talk to.
    #
    # Adding an adapter is a class in app/datasource/ and a line in its
    # ADAPTERS map; nothing in the core telemetry logic changes.
    data_source: str = Field(
        default="sqlite",
        description="sqlite | sql | influxdb | grafana. The habitat backend.",
    )

    # --- Grafana adapter: reach InfluxDB through Grafana --------------------

    grafana_url: str = Field(default="", description="Base URL, no trailing slash.")
    grafana_token: str = Field(default="", description="Service-account token.")
    grafana_user: str = ""
    grafana_pass: str = ""
    grafana_datasource_uid: str = ""

    # --- Direct InfluxDB adapter: connect to InfluxDB without Grafana ------

    influx_url: str = Field(default="", description="InfluxDB base URL, no trailing slash.")
    influx_token: str = Field(default="", description="InfluxDB 1.8+ token. Or use user/pass.")
    influx_user: str = ""
    influx_pass: str = ""

    # The database to query. Required for the direct adapter; optional for the
    # Grafana adapter, which otherwise discovers it from the datasource
    # definition — set it there only if that discovery fails.
    influx_db: str = ""

    datasource_timeout: int = Field(
        default=20, ge=1, le=300, description="Seconds to wait on a habitat-database call."
    )

    # --- SQLite adapter: read a local file in the canonical readings schema -

    # Path to a SQLite database with a `readings(measurement, location, field,
    # ts, value)` table. Relative paths resolve against the backend directory.
    # See app/datasource/sqlite.py for the schema and scripts/seed_demo_sqlite.py
    # to build the shipped demo habitat.
    sqlite_path: str = ""

    # --- SQL adapter: map onto an existing relational database -------------

    # A DB-API DSN: sqlite:///path.db | postgresql://user:pass@host/db |
    # mysql://user:pass@host/db. The table/column mapping lives in the habitat
    # profile's `sql_mapping:` section. See app/datasource/sql.py.
    sql_dsn: str = ""

    # --- Habitat profile: the sensors, zones and units of THIS habitat -----

    # Path to a habitat profile (YAML). Everything mission-specific — the
    # habitat's display name, its rooms, sensor units, tanks, meters and
    # dashboard panels — lives there, not in code. Relative paths resolve
    # against the backend directory.
    #
    # There is no default habitat: blank means no profile, so units read as
    # unrecorded and the dashboard is derived from the database. Point this at
    # one of config/examples/ or your own copy.
    habitat_config: str = ""

    # --- Knowledge base ----------------------------------------------------

    # Where uploaded documents are kept. Relative paths resolve against the
    # backend directory. Retrieved passages go to the selected model provider.
    knowledge_dir: str = "knowledge"

    # The Ollama model used to embed passages. Pull it with
    # `ollama pull nomic-embed-text`. Without it the knowledge base still works,
    # falling back to lexical search, and the interface says so.
    embedding_model: str = "nomic-embed-text"

    # Largest document accepted, in megabytes.
    max_upload_mb: int = Field(default=25, ge=1, le=100)

    # --- Optional local voice interface -----------------------------------

    # Voice processing runs as local child processes. ATLAS never uploads
    # recordings or answers to a speech service. Models are deliberately not
    # bundled because their licenses and size vary; operators opt in by
    # pointing these fields at locally installed whisper.cpp and Piper models.
    voice_whisper_cli: str = "whisper-cli"
    voice_whisper_model: str = "models/ggml-tiny.bin"
    voice_whisper_language: str = "auto"
    voice_whisper_threads: int = Field(default=4, ge=1, le=16)
    voice_ffmpeg_cli: str = "ffmpeg"
    voice_piper_cli: str = "piper"
    voice_piper_model: str = "models/en_US-lessac-medium.onnx"
    voice_max_upload_mb: int = Field(default=12, ge=1, le=50)
    voice_timeout: int = Field(default=180, ge=10, le=600)

    # How many passages are handed to the model for one question.
    knowledge_results: int = 6

    # --- Which model answers ----------------------------------------------

    # `ollama` runs the model on this machine and makes no API calls at all;
    # `anthropic` calls the cloud. This is the fallback: whatever was last
    # chosen on the /models page is stored in the database and wins over it.
    llm_provider: str = Field(
        default="ollama", description="ollama | anthropic. The default provider."
    )

    # --- Ollama (the local runtime) ---------------------------------------

    ollama_host: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:8b"

    # Context window, in tokens.
    #
    # Ollama's own default is 4096, which this application cannot run in. The
    # system prompt is ~2,600 tokens and the thirteen tool definitions another
    # ~5,000, so roughly 7,600 tokens are spent before the question is read —
    # and they go up again on every round of every turn. At 4096 the tools
    # alone would not fit and the model would answer without them, which is to
    # say it would answer without reading a sensor.
    ollama_num_ctx: int = 16384

    ollama_max_tokens: int = Field(
        default=4096, description="Cap on one answer. -1 for the model's own limit."
    )

    # Low, because every number in an answer has to be the one the query
    # returned. This is not a task where invention helps.
    ollama_temperature: float = 0.2

    # How long a loaded model stays in memory after a question. Reloading 5 GB
    # of weights per question is the difference between two seconds and thirty.
    ollama_keep_alive: str = "30m"

    # Generous: a first question loads the weights from disk, and a small model
    # on CPU is not quick.
    ollama_timeout: int = 600

    ollama_thinking: str = Field(
        default="auto",
        description=(
            "auto | disabled. Auto turns on visible reasoning for the models "
            "that support it and leaves it off for the ones that do not."
        ),
    )

    # Where Ollama keeps the weights it downloads. Display only — the running
    # Ollama server decides this from its own OLLAMA_MODELS environment
    # variable, so setting it here without setting it there changes nothing.
    ollama_models_dir: str = ""

    # --- Anthropic --------------------------------------------------------

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5"
    anthropic_max_tokens: int = 8192
    anthropic_effort: str = Field(
        default="medium",
        description="low | medium | high | xhigh | max. Depth of reasoning.",
    )
    anthropic_thinking: str = Field(
        default="adaptive",
        description="adaptive | disabled. Adaptive lets the model decide.",
    )

    # --- Agent loop -------------------------------------------------------

    max_tool_rounds: int = Field(
        default=10,
        description="How many query/answer cycles one question may take.",
    )

    # --- Conversation store ----------------------------------------------

    # Chat history is kept in SQLite next to the app, so it survives restarts.
    # Relative paths resolve against the backend directory.
    database_path: str = "atlas.db"

    # How many stored messages of a thread are replayed to the model. The
    # whole thread is kept on disk regardless — this only bounds the context
    # sent with each request.
    max_turns_per_conversation: int = 200

    # Threads listed in the sidebar, newest first.
    max_conversations_listed: int = 200

    # --- HTTP service -----------------------------------------------------

    allowed_hosts: str = "localhost,127.0.0.1,[::1]"
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"
    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        description="Comma-separated list of allowed browser origins.",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def grafana_base(self) -> str:
        return self.grafana_url.rstrip("/")

    @property
    def has_grafana_credentials(self) -> bool:
        return bool(self.grafana_token or (self.grafana_user and self.grafana_pass))

    @property
    def influx_base(self) -> str:
        return self.influx_url.rstrip("/")

    @property
    def resolved_knowledge_dir(self) -> Path:
        """Where uploaded documents live, absolute."""
        path = Path(self.knowledge_dir).expanduser()
        if path.is_absolute():
            return path
        return (Path(__file__).resolve().parents[1] / path).resolve()

    @property
    def resolved_sqlite_path(self) -> Path:
        """The SQLite habitat file, absolute (relative paths from backend root)."""
        path = Path(self.sqlite_path or "habitat.db").expanduser()
        if path.is_absolute():
            return path
        return (Path(__file__).resolve().parents[1] / path).resolve()

    @property
    def datasource_configured(self) -> bool:
        """True when the SELECTED adapter has what it needs to connect.

        Transport-agnostic: the health endpoint and startup log ask this
        rather than naming Grafana, so a different adapter reports correctly.
        """
        which = (self.data_source or "sqlite").strip().lower()
        if which == "influxdb":
            return bool(self.influx_base and self.influx_db)
        if which == "sqlite":
            return self.resolved_sqlite_path.exists()
        if which == "sql":
            return bool(self.sql_dsn)
        return bool(self.grafana_base and self.has_grafana_credentials)

    @property
    def datasource_summary(self) -> str:
        """One line naming where the habitat data comes from, for logs."""
        which = (self.data_source or "sqlite").strip().lower()
        if which == "influxdb":
            base = self.influx_base or "(unset)"
            return f"influxdb -> {base} db={self.influx_db or '(unset)'}"
        if which == "sqlite":
            return f"sqlite -> {self.resolved_sqlite_path}"
        if which == "sql":
            scheme = (self.sql_dsn.split("://", 1)[0] if self.sql_dsn else "(unset)")
            return f"sql -> {scheme}://…"
        return (
            f"grafana -> {self.grafana_base or '(unset)'} "
            f"datasource={self.grafana_datasource_uid or '(unset)'}"
        )

    @property
    def ollama_base(self) -> str:
        return self.ollama_host.rstrip("/")

    @property
    def resolved_ollama_models_dir(self) -> str:
        """Where the weights land, as best we can tell from here.

        Ollama's own setting is what actually decides this. We report the
        configured path, then the OLLAMA_MODELS the server would read if it
        was started from this environment, then Ollama's default.
        """
        if self.ollama_models_dir:
            return str(Path(self.ollama_models_dir).expanduser())
        from_env = os.environ.get("OLLAMA_MODELS", "")
        if from_env:
            return str(Path(from_env).expanduser())
        return str(Path.home() / ".ollama" / "models")

    @property
    def resolved_database_path(self) -> Path:
        """The SQLite file, absolute, so it does not follow the working dir."""
        path = Path(self.database_path).expanduser()
        if path.is_absolute():
            return path
        # config.py lives in app/, so the backend root is one level up.
        return (Path(__file__).resolve().parents[1] / path).resolve()

    def thinking_param(self) -> dict:
        """The `thinking` argument for the Messages API."""
        if self.anthropic_thinking.lower() == "disabled":
            return {"type": "disabled"}
        return {"type": "adaptive", "display": "summarized"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """The process-wide settings singleton."""
    return Settings()
