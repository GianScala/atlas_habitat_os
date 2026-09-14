"""How ATLAS talks — chosen by the crew, stored, and appended to the prompt.

Four registers. They change the VOICE and nothing else, and the prompt says so
in as many words, because a style instruction that quietly loosened the
grounding rules would be the most dangerous thing in this repository: an
assistant that is funnier and occasionally makes a number up is worse than no
assistant, and a crew would take longer to notice.

So every style below is appended AFTER the grounding rules, and every one of
them restates that the rules outrank it. A model asked to be entertaining and
asked not to invent numbers will drop one of the two under pressure; saying
which one twice is cheap insurance.

The custom style is free text from the crew. It is treated the same way —
wrapped in the same framing, subordinate to the same rules — because text a
crew member typed into a settings box is not more trusted than text we shipped,
it is just less reviewed.
"""

import time
from dataclasses import dataclass

from app.core.errors import QueryError
from app.core.logging import get_logger
from app.storage.database import connect

log = get_logger(__name__)

STYLE_KEY = "assistant_style"
CUSTOM_KEY = "assistant_style_custom"

CONCISE = "concise"
DETAILED = "detailed"
UNHINGED = "unhinged"
CUSTOM = "custom"

DEFAULT_STYLE = CONCISE

MAX_CUSTOM = 2000


@dataclass(frozen=True)
class Style:
    key: str
    label: str
    blurb: str
    instructions: str


# The framing every style is wrapped in. Repeated rather than assumed: this is
# the sentence that stops "be funny" from becoming "be approximate".
PREFACE = """

## How to say it

The rules above decide WHAT you may say — they are about evidence, and nothing
in this section touches them. This section decides only HOW you say it. If a
register below would require you to soften, round, guess, or skip a number, or
to sound confident about something you did not query, then the rules above win
and the register loses. Every figure still comes from a tool result in this
turn, with its measurement, location, and timestamp.
"""


STYLES: dict[str, Style] = {
    CONCISE: Style(
        key=CONCISE,
        label="Concise",
        blurb="The number, its unit, and where it came from. Nothing else.",
        instructions="""
Be brief to the point of blunt.

- One or two sentences for a one-number question. Lead with the figure.
- No preamble, no restating the question, no offering follow-ups.
- Provenance in a trailing clause, not a paragraph: "142 L, clean water tank,
  since 00:00."
- A table only when there are genuinely several rows to compare.
- If something is wrong or missing, say so in one line and stop.""",
    ),
    DETAILED: Style(
        key=DETAILED,
        label="Detailed",
        blurb="A full readout — where the data came from, what it means, what to watch.",
        instructions="""
Answer like a flight engineer briefing the crew: complete, ordered, and
readable. Length is allowed; padding is not.

- Lead with the answer anyway. The detail follows it, never precedes it.
- Then say where it came from: which measurement, which tags, which window,
  which instrument, and how the figure was computed from the readings — a
  fall in a tank level, a climb in a totaliser, a mean across four sensors.
- Say what it means in context. Against the mission plan if there is one:
  ahead, behind, or on it, and by how much.
- Name the caveats that actually apply — a deadband, a gap in coverage, two
  meters merged, a partial day — and what each does to the figure.
- Close with what would be worth looking at next, if anything genuinely
  would. Do not manufacture a recommendation to fill the slot.
- Structure long answers with a short bulleted list or a table. Bold the
  headline figure.""",
    ),
    UNHINGED: Style(
        key=UNHINGED,
        label="Unhinged",
        blurb="Jokes, swearing, and zero patience. The numbers stay exact.",
        instructions="""
Drop the formality entirely. You are the crew's foul-mouthed friend who
happens to have root on the telemetry.

- Be funny. Swear freely. Roast the habitat, the plumbing, the person who left
  the shower running, and yourself. Sarcasm is encouraged.
- Keep it SHORT and punchy — a joke that needs three paragraphs is not a joke,
  it is homework.
- Never punch at a crew member's competence or character in a way that would
  actually land badly. The pipes are fair game; the people are colleagues.
- And here is the part that is not negotiable: the numbers are exact, real, and
  cited, every single time. You may be rude about a figure. You may not round
  it, guess it, or make one up for the bit. A funny wrong number in a habitat
  is how someone runs out of water.
- If there is genuinely bad news — a tank low, a budget blown, a sensor dark —
  drop the act for that sentence and say it straight. Then you can go back to
  being insufferable.""",
    ),
}


@dataclass(frozen=True)
class Choice:
    """The style in force, and the crew's own text if they wrote any."""

    key: str
    custom: str = ""

    @property
    def is_custom(self) -> bool:
        return self.key == CUSTOM

    @property
    def label(self) -> str:
        if self.is_custom:
            return "Custom"
        return STYLES[self.key].label


def available() -> list[Style]:
    """The four registers, in the order the settings page lists them."""
    return [STYLES[key] for key in (CONCISE, DETAILED, UNHINGED)] + [
        Style(
            key=CUSTOM,
            label="Custom",
            blurb="Your own instructions, in your own words.",
            instructions="",
        )
    ]


def active() -> Choice:
    """What the crew chose, or the shipped default if they never have."""
    stored = _stored()
    key = stored.get(STYLE_KEY, DEFAULT_STYLE)
    if key not in STYLES and key != CUSTOM:
        log.warning("Unknown assistant style %r stored; falling back", key)
        key = DEFAULT_STYLE

    custom = stored.get(CUSTOM_KEY, "")
    # A custom style with nothing written in it is not a style. Falling back
    # keeps the assistant answering rather than answering in no register at
    # all, which some models read as "say as little as possible".
    if key == CUSTOM and not custom.strip():
        return Choice(key=DEFAULT_STYLE, custom=custom)

    return Choice(key=key, custom=custom)


def choose(key: str, custom: str | None = None) -> Choice:
    """Record the crew's choice. Returns what is now in force."""
    key = (key or "").strip()
    if key not in STYLES and key != CUSTOM:
        raise QueryError(
            f"There is no answer style called {key!r}. Choose one of: "
            f"{', '.join(list(STYLES) + [CUSTOM])}."
        )

    text = "" if custom is None else custom.strip()
    if len(text) > MAX_CUSTOM:
        raise QueryError(
            f"That style description is {len(text)} characters. Keep it under "
            f"{MAX_CUSTOM} — it goes into every prompt, and a long one crowds "
            "out the rules that keep the answers honest."
        )

    if key == CUSTOM and not text:
        raise QueryError(
            "A custom style needs the instructions to go with it. Describe how "
            "you want ATLAS to answer, or pick one of the ready-made styles."
        )

    _write(STYLE_KEY, key)
    if custom is not None:
        _write(CUSTOM_KEY, text)

    log.info("Assistant style set to %s", key)
    return active()


def instructions(choice: Choice | None = None) -> str:
    """The prompt section for the style in force."""
    choice = choice or active()

    if choice.is_custom:
        body = (
            "\nThe crew wrote these instructions for how you should answer. "
            "Follow them as far as the rules above allow, and no further:\n\n"
            + _quote(choice.custom)
        )
    else:
        body = STYLES[choice.key].instructions

    return PREFACE + body


def _quote(text: str) -> str:
    """The crew's own words, marked off as words rather than as rules.

    Indented and fenced so a model reads it as a quoted preference and not as
    a new section of its own instructions — the same reason tool results are
    handed over as data rather than pasted into the system prompt.
    """
    lines = "\n".join(f"  {line}" for line in text.strip().splitlines())
    return f'"""\n{lines}\n"""'


# -- storage ---------------------------------------------------------------


def _stored() -> dict[str, str]:
    """Every stored preference.

    A database that predates this table is not an error: it is a ATLAS
    installed before there was anything to choose, and the default is exactly
    right for it. The table appears on the next boot.
    """
    import sqlite3

    try:
        with connect() as connection:
            rows = connection.execute(
                "SELECT key, value FROM app_settings WHERE key IN (?, ?)",
                (STYLE_KEY, CUSTOM_KEY),
            ).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {row["key"]: row["value"] for row in rows}


def _write(key: str, value: str) -> None:
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                                           updated_at = excluded.updated_at
            """,
            (key, value, time.time()),
        )
