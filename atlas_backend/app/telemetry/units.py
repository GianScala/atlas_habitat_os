"""Units — the one thing about the schema we cannot discover.

InfluxDB 1.x stores no unit metadata, so units have to come from somewhere
else. They live in the habitat profile (`app.habitat`, a YAML file), read off
the habitat's dashboards and trusted. This module is a thin view over that.

A unit we have not verified is reported as unknown rather than guessed, and the
model is instructed to give the bare number in that case. Inventing a dimension
for a number is a way of being confidently wrong. What is NOT allowed anywhere
is inferring a unit from a field's NAME.

To extend the table, edit the habitat profile's `units:` section;
`config/examples/habitat.example.yaml` documents the format. For a habitat
behind Grafana, `scripts/inspect_dashboards.py` prints a paste-ready block from
the units its panels actually render in — a dashboard is evidence, a field name
is not.
"""

from app.habitat import profile

# Electrical fields where summing across phases is not physically meaningful.
# Sourced from the habitat profile; defaults to none when unspecified.
NON_SUMMABLE_FIELDS = profile().non_summable_fields


def unit_for(measurement: str, field: str) -> tuple[str, str]:
    """(unit, source) where source is 'known' or 'unknown'.

    We never guess. An unknown unit is reported as unknown so the answer can
    give the bare number instead of inventing a dimension for it.
    """
    return profile().unit_for(measurement, field)
