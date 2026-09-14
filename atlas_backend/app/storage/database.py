"""SQLite connection handling and schema.

Chat history outlives the process, so it lives on disk. SQLite is the right
size for this: no service to run, no network hop, and a habitat deployment is
one process on one machine.

Connections are opened per operation rather than shared. FastAPI runs sync
endpoints in a threadpool, so a single shared connection would need locking
around every call; opening one is cheap (microseconds against a local file)
and sidesteps the whole class of cross-thread problems.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from app.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL
                    REFERENCES conversations(id) ON DELETE CASCADE,
    position        INTEGER NOT NULL,
    role            TEXT NOT NULL,
    -- The message's `content` as the Messages API wants it back: either a
    -- plain string or a list of content blocks, stored as JSON.
    content         TEXT NOT NULL,
    created_at      REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation
    ON messages(conversation_id, position);

CREATE INDEX IF NOT EXISTS idx_conversations_updated
    ON conversations(updated_at DESC);

-- The crew's ceiling per resource: the most that may be drawn across the whole
-- mission. A row here is a figure someone decided; its ABSENCE means nobody
-- has. That is the whole provenance mechanism, and it has no third state to
-- get out of step: resetting the plan is deleting rows.
--
-- Everything else — a day's allowance, a cycle's, what is left — is derived
-- from this and the mission's length by `mission/dayplan.py`, and is therefore
-- never stored. Storing a derived figure is how it comes to disagree with what
-- it was derived from.
CREATE TABLE IF NOT EXISTS mission_totals (
    resource    TEXT PRIMARY KEY,
    -- NULL is a deliberate "we are not capping this one", which is different
    -- from an absent row: it is the crew saying they looked and chose not to.
    total       REAL,
    updated_at  REAL NOT NULL
);

-- Planned consumption the flat daily rate does not cover: the water an
-- experiment takes on MD-14, the power the dishwasher draws every day. Carved
-- out of the ceiling above rather than added to it.
CREATE TABLE IF NOT EXISTS mission_extras (
    id          TEXT PRIMARY KEY,
    resource    TEXT NOT NULL,
    label       TEXT NOT NULL,
    amount      REAL NOT NULL,
    -- 'once' (on on_date) or 'daily' (every day of the mission).
    kind        TEXT NOT NULL,
    -- The local date a one-off lands on; NULL for a daily one.
    on_date     TEXT,
    note        TEXT NOT NULL DEFAULT '',
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mission_extras_resource
    ON mission_extras(resource, on_date);

-- The mission itself — name, first day, length — and the habitat's day
-- boundary. One row per fact, so a partly-declared mission is representable
-- and the interface can say which part is missing.
CREATE TABLE IF NOT EXISTS mission_settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  REAL NOT NULL
);

-- The crew's own meter rounds: one row per dial, per mission day, per round.
--
-- A row is a READING off a meter face — a cumulative total in kWh or m3 — and
-- never a consumption. Consumption is the difference between two rows, derived
-- on every read by `mission/logbook.py`, for the same reason no allowance is
-- stored: a stored derivation is a figure that will eventually disagree with
-- what it was derived from, silently.
--
-- Keyed by MISSION DAY rather than by date, because MD-03 is what is written at
-- the top of the clipboard page. Moving the mission's start date therefore
-- moves the whole log with it instead of stranding it in the calendar.
CREATE TABLE IF NOT EXISTS mission_readings (
    resource    TEXT NOT NULL,     -- 'power' | 'water'
    meter       TEXT NOT NULL,     -- a room key, or a tap key
    day_index   INTEGER NOT NULL,  -- 1 is MD-01
    -- Which round it was taken on: 'morning'/'evening' for power, 'daily' for
    -- water. A position on the rounds, not a clock time.
    slot        TEXT NOT NULL,
    value       REAL NOT NULL,
    updated_at  REAL NOT NULL,
    PRIMARY KEY (resource, meter, day_index, slot)
);

CREATE INDEX IF NOT EXISTS idx_mission_readings_day
    ON mission_readings(resource, day_index);

-- Choices made in the interface that must outlive the process — at present,
-- which model answers questions. A row here beats the .env default; no row
-- means nobody has chosen and the .env value stands.
CREATE TABLE IF NOT EXISTS app_settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  REAL NOT NULL
);

-- What the crew calls the things the database names.
--
-- The database is read-only and its vocabulary is whatever the habitat's
-- engineers chose: a room may be tagged `Container3`, `2B`, or `crew_room`.
-- A row here renames one of those FOR DISPLAY only; nothing is ever written
-- back to the habitat database, and queries still use the real tag value.
--
-- `kind` is 'location' or 'measurement'. A row beats the habitat profile's
-- zone_names, which beats the raw value.
CREATE TABLE IF NOT EXISTS display_labels (
    kind        TEXT NOT NULL,
    key         TEXT NOT NULL,
    label       TEXT NOT NULL,
    updated_at  REAL NOT NULL,
    PRIMARY KEY (kind, key)
);

-- Documents the crew has attached as a knowledge base: procedures, emergency
-- contact sheets, checklists. The file itself is saved under KNOWLEDGE_DIR; this
-- row is its identity, and `connected` is whether the assistant may search it.
CREATE TABLE IF NOT EXISTS knowledge_documents (
    id          TEXT PRIMARY KEY,
    filename    TEXT NOT NULL,
    kind        TEXT NOT NULL,          -- PDF | Word document | CSV | ...
    bytes       INTEGER NOT NULL,
    characters  INTEGER NOT NULL,
    chunks      INTEGER NOT NULL,
    indexing    TEXT NOT NULL,          -- vector | lexical
    connected   INTEGER NOT NULL DEFAULT 1,
    note        TEXT NOT NULL DEFAULT '',
    uploaded_at REAL NOT NULL
);

-- One retrievable passage. `embedding` is a JSON array when the passage was
-- indexed with an embedding model, and NULL when it was indexed lexically.
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    document_id TEXT NOT NULL,
    ordinal     INTEGER NOT NULL,
    text        TEXT NOT NULL,
    embedding   TEXT,
    PRIMARY KEY (document_id, ordinal),
    FOREIGN KEY (document_id) REFERENCES knowledge_documents(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_document
    ON knowledge_chunks(document_id);

-- The dials the crew walks round and reads by hand.
--
-- Which rooms and taps a habitat sub-meters is a fact about its plumbing and
-- wiring, so the crew maintains the list here rather than it being shipped in
-- the source. Empty means the habitat profile's list stands; any row here
-- replaces it wholesale, so a habitat can add, rename, reorder, or drop dials.
CREATE TABLE IF NOT EXISTS crew_meters (
    resource     TEXT NOT NULL,          -- power | water
    key          TEXT NOT NULL,          -- stable id, never shown
    label        TEXT NOT NULL,
    code         TEXT NOT NULL DEFAULT '',
    grouping     TEXT NOT NULL DEFAULT '',
    group_label  TEXT NOT NULL DEFAULT '',
    stream       TEXT NOT NULL DEFAULT 'none',
    position     INTEGER NOT NULL DEFAULT 0,
    updated_at   REAL NOT NULL,
    PRIMARY KEY (resource, key)
);
"""


# Changes to data that has already been written. Every statement here must be
# safe to run on every boot, because it is.
MIGRATIONS = """
-- Water used to be read once a day, on a round called 'daily'; it is now read
-- morning and evening like the power sub-meters. A row left on the old round
-- would still be on disk and no longer on any sheet — invisible, and silently
-- absent from every total. Lifting them onto the morning round keeps the
-- reading, which is a fact: a dial did say that.
--
-- It does NOT recover the consumption. Every block runs from a morning to an
-- evening or from an evening to a morning, so readings that all sit on one
-- round close nothing, and those days report as gaps until an evening round is
-- walked. That is the honest outcome. The alternative — copying each reading
-- onto both rounds to preserve the day's total — would put the whole day's
-- draw on one side of a split nobody measured.
UPDATE mission_readings
   SET slot = 'morning'
 WHERE resource = 'water'
   AND slot = 'daily'
   AND NOT EXISTS (
       SELECT 1 FROM mission_readings AS existing
        WHERE existing.resource = 'water'
          AND existing.meter = mission_readings.meter
          AND existing.day_index = mission_readings.day_index
          AND existing.slot = 'morning'
   );

-- Any that could not be lifted because a morning reading was already there are
-- duplicates of a round now recorded twice. The newer figure is the one the
-- crew entered on the current sheet, so the stranded old row goes.
DELETE FROM mission_readings WHERE resource = 'water' AND slot = 'daily';
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """A connection for one unit of work, committed or rolled back on exit."""
    settings = get_settings()
    connection = sqlite3.connect(settings.resolved_database_path, timeout=10.0)
    connection.row_factory = sqlite3.Row

    # Write-ahead logging lets readers run while a write is in flight, which
    # matters because a streaming answer writes as the sidebar reads.
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")

    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialise() -> None:
    """Create the schema if it is not there. Safe to call on every boot."""
    settings = get_settings()
    path = settings.resolved_database_path
    path.parent.mkdir(parents=True, exist_ok=True)

    with connect() as connection:
        connection.executescript(SCHEMA)
        connection.executescript(MIGRATIONS)

    log.info("Chat history database ready at %s", path)
