"""The mission plan: what the crew decided to consume, and what they did.

Everything else in this backend reports what the habitat DID. This package is
the only part that holds a number nobody measured — an intention — and puts
the two side by side.

That distinction is the reason it is its own folder rather than another panel
in `services/dashboard.py`. A dashboard panel is telemetry; a budget is a
decision, and the two have different provenance, different lifetimes, and
different ways of being wrong. Mixing them in one module would have made it
easy to lose track of which numbers came from a sensor.

    plan.py        the horizons, the shipped defaults, and validation
    meters.py      which instrument answers "how much did we use"
    periods.py     when today, this cycle, and this week begin and end
    repository.py  the crew's own plan, on disk
    tracking.py    the two put together: used, budgeted, and on pace or not

The rule the rest of the codebase follows holds here too. A budget may be a
default we shipped, but a CONSUMPTION figure is only ever a query result —
there is no estimate, no carry-forward, and no filling in of a period the
sensors did not cover. Where a figure cannot be had, the payload says so.
"""
