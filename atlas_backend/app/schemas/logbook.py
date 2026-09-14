"""Shapes for the crew's meter log.

Mirrored in `atlas_frontend/src/lib/types.ts`. As with `mission.py`, this file
is the source of truth: FastAPI drops any key the response model does not
declare, silently.

The distinction the whole contract is built around: a `ReadingEntry` is what
somebody typed off a dial, and a `BlockUsage` is what this backend worked out
from two of them. They are never merged into one field, for the same reason
`planned` and `actual` never are on the mission plan — one is a record and the
other is a derivation, and a page that cannot tell them apart cannot say which
of the two is wrong.
"""


from pydantic import BaseModel


class LogMeter(BaseModel):
    """One dial on one wall, as the sheet lists it."""

    key: str
    label: str
    # The tag on the pipe — `2R`. Empty for the power sub-meters, which are
    # named by their room and need no second identifier.
    code: str = ""
    # What it serves: sink, shower, toilet… Used to collapse eleven taps onto
    # a number of slices a reader can actually tell apart.
    group: str = ""
    group_label: str = ""
    # warm | cold | none.
    stream: str = "none"


class LogSlot(BaseModel):
    """One position on the rounds — not a clock time.

    Carries two names because a round and the consumption it opens are two
    different things. `label` is the walk somebody takes to the dial, and heads
    the column a reading is typed into. `block_label` is what was drawn between
    that walk and the next one, and titles every derived figure on the page.
    """

    key: str
    # "Morning round" — the walk.
    label: str
    # "Daytime" — the consumption it opens.
    block_label: str = ""
    # The span in words: "evening round to the next morning's round".
    covers: str = ""


class ReadingEntry(BaseModel):
    """One figure the crew typed off a meter face. Cumulative, never a delta."""

    meter: str
    day_index: int
    slot: str
    value: float
    updated_at: float = 0.0


class BlockUsage(BaseModel):
    """What was drawn between two readings — derived here, never stored.

    In the REPORTED unit, so water arrives in litres however it was typed.
    """

    meter: str
    day_index: int
    slot: str
    amount: float | None = None
    # ok | open | gap | backwards. `open` is waiting on a closing reading,
    # `gap` is a round that happened and was not written down, and `backwards`
    # is a meter that appears to have counted down.
    status: str = "open"
    opens: float | None = None
    closes: float | None = None
    # Which mission day supplies the closing reading, where one can exist.
    closes_code: str | None = None


class LoggedDay(BaseModel):
    """One mission day on the sheet, and what has been derived for it."""

    index: int
    code: str
    date: str
    # past | today | future
    state: str
    total: float | None = None
    blocks_logged: int = 0
    blocks_expected: int = 0
    # False while any of the day's blocks is still waiting on its closing
    # reading. Every figure drawn from an incomplete day is provisional.
    complete: bool = False


class Share(BaseModel):
    """One slice: an amount, and what fraction of the window it is."""

    key: str
    label: str
    code: str = ""
    # Set on the day/night split, where the slice is a span of hours and the
    # span is worth stating beside it.
    covers: str = ""
    amount: float = 0.0
    # None where the window's total is zero or unknown — a share of nothing is
    # not zero percent, it is undefined, and drawing it as 0% is a claim.
    share: float | None = None
    # False where this meter has nothing logged in the window at all, which is
    # a different thing from a meter that logged zero.
    logged: bool = True


class LogWindow(BaseModel):
    """One window of the analysis: the total, and every way it splits.

    Windows end at the LAST LOGGED DAY, not at today, so that a morning before
    the rounds are walked does not look like a collapse in consumption.
    """

    key: str
    label: str
    first_code: str | None = None
    last_code: str | None = None
    days_covered: int = 0
    days_in_window: int = 0
    total: float | None = None
    per_day_mean: float | None = None
    complete: bool = False
    meters: list[Share] = []
    groups: list[Share] = []
    streams: list[Share] = []
    slots: list[Share] = []


class LogCoverage(BaseModel):
    """How much of the sheet is filled in.

    `expected` counts only rounds that have already happened — the figure the
    crew is actually judged against. `total` counts the whole mission.
    """

    filled: int = 0
    total: int = 0
    expected: int = 0
    expected_filled: int = 0


class LogResource(BaseModel):
    """One resource's sheet and everything derived off it."""

    key: str
    label: str
    # What the input box takes — m³ for water, off the dial.
    entry_unit: str
    # What every figure below is reported in — litres for water.
    unit: str
    slots: list[LogSlot] = []
    meters: list[LogMeter] = []
    entries: list[ReadingEntry] = []
    usage: list[BlockUsage] = []
    days: list[LoggedDay] = []
    latest_day: int | None = None
    windows: list[LogWindow] = []
    coverage: LogCoverage = LogCoverage()
    # Meters that appear to have counted down, said in full: both days either
    # side of one are left out of every total until it is corrected.
    issues: list[str] = []


class LogMission(BaseModel):
    """Just enough of the mission to lay out a sheet and title it."""

    is_declared: bool = False
    name: str = ""
    start: str | None = None
    end: str | None = None
    days: int | None = None
    today: str = ""
    day_index: int | None = None
    day_code: str | None = None


class Logbook(BaseModel):
    """Everything the crew-log page draws."""

    generated_at: str
    day_start_label: str
    mission: LogMission
    days: list[LoggedDay] = []
    resources: list[LogResource] = []


class ReadingWrite(BaseModel):
    """One box on the sheet, as the interface sends it.

    A null `value` clears the box. That is not a convenience: a mistyped
    reading corrupts the blocks on both sides of it, so withdrawing one has to
    be an available move.
    """

    resource: str
    meter: str
    day_index: int
    slot: str
    value: float | None = None
