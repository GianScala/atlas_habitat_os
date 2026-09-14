"""Instrument noise floors — the other thing the schema cannot tell us.

InfluxDB records a number and a timestamp. It does not record how much of
that number the instrument can actually be trusted for. That matters nowhere
for a level reading and enormously for a level DIFFERENCE: differencing
amplifies noise, and any one-sided accounting of the differences (a tank's
falls read as consumption, its rises as refill) turns symmetric noise into a
steady stream of use that never happened.

The size of the effect is not marginal. On a tank sampled every minute,
differencing raw samples over three days can report well over a kilolitre of
movement on a tank that actually moved a few hundred litres. Most of that
"consumption" is gauge dither.

Two mechanisms defend against it, and they do different jobs:

  BUCKETING averages many samples into one level, which suppresses isolated
  outliers and per-sample dither. It is the larger effect by far.

  A DEADBAND, applied with hysteresis against a held reference, rejects what
  survives — the slow wobble of a tank that is sitting still. See the deadband
  note in `timeseries.py` for why it is held against a reference rather than
  against the previous bucket.

The deadband is a property of the instrument, not of the question, so it is
configuration rather than an argument at each call site. One table, read by the
dashboard and by the chat tools alike: a chart and an answer built from the same
gauge have to agree, and they cannot if each picks its own threshold.

DERIVING ONE FOR YOUR HABITAT. A floor is measured, never guessed — a guess
either invents consumption or silently erases it, and the answer looks identical
either way. Take a quiescent stretch of a few hours where the tank demonstrably
did not move, bucket the readings as the charts do, and look at the size of the
steps that remain: the floor wants to clear the median comfortably and to cover
the gauge's quantisation step, without being so large it swallows a real draw.
Then check what it costs — a good floor takes a few litres off a few hundred,
while rejecting the fiction above. Put the result in the habitat profile's
`noise_floors:` section.

Worth re-deriving from a longer sample, and worth revisiting if a gauge
is replaced. A field with no entry here is reported as unknown rather than
given a plausible-looking default — the same rule units.py follows, and for
the same reason.
"""


from app.habitat import profile


def deadband_for(measurement: str, field: str) -> tuple[float, str]:
    """(deadband, source) where source is 'measured' or 'unknown'.

    The measured noise floors are habitat-specific (they come from a particular
    gauge), so they live in the habitat profile's `noise_floors:` section rather
    than in code. An instrument with no declared floor gets 0.0 — every reading
    trusted exactly as it comes — and the caller is expected to say so. Guessing
    a threshold would either invent consumption or silently erase it, and there
    is no way to tell from the answer which one happened.
    """
    floor = profile().noise_floor(measurement, field)
    if floor is None:
        return 0.0, "unknown"
    return floor, "measured"


def resolve_deadband(
    measurement: str, field: str, override: float | None = None
) -> tuple[float, str]:
    """The deadband to use, honouring an explicit override.

    An override is taken at face value and labelled as caller-supplied, so an
    answer can always say where its threshold came from.
    """
    if override is None:
        return deadband_for(measurement, field)
    if override < 0:
        raise ValueError(f"Deadband must not be negative, got {override!r}.")
    return float(override), "caller"
