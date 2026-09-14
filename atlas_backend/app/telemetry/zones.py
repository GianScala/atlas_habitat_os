"""Human names for habitat zones, and the tag keys that name a place.

A thin view over the habitat profile (`app.habitat`). The data — which tag
values map to which room name, which tag keys name a place, which measurement
prefixes are the database's own internal metrics — lives in the habitat's YAML
profile, not here, so a new mission renames its rooms without touching code.

The zone table is a translation table, never a claim that a zone currently
reports data. Zones absent from it still work — the model just uses the tag
value directly, and describe() reports the real set at runtime.

The public names here (`ZONE_NAMES`, `LOCATION_TAG_KEYS`, `INTERNAL_PREFIXES`,
`is_internal`, `zone_names_for`, `case_variants`) are unchanged, so every caller
keeps working; only their source moved into configuration.
"""

from app.habitat import profile

# Resolved once at import from the active habitat profile. A profile is fixed
# for the life of the process (a habitat does not rename its rooms mid-session),
# so these are module constants exactly as they used to be — the values now come
# from YAML instead of a literal.
_profile = profile()

# Tag keys that name a place, most specific first. Used to pick a default
# grouping tag for a measurement we have not seen before.
LOCATION_TAG_KEYS = _profile.location_tag_keys

# Measurement-name prefixes that identify the database's OWN metrics (InfluxDB
# writes metrics about itself into the same database) so they stay out of the
# habitat sensor list.
INTERNAL_PREFIXES = _profile.internal_prefixes

# Tag value -> human room/zone name. Where two tag values name the SAME physical
# place they map to the same string, which is what lets the dashboard give a
# room one colour across every chart.
ZONE_NAMES: dict[str, str] = dict(_profile.zone_names)


def is_internal(measurement: str) -> bool:
    """True for the database's own metrics rather than a habitat sensor."""
    return bool(INTERNAL_PREFIXES) and measurement.startswith(INTERNAL_PREFIXES)


def zone_names_for(values: list[str]) -> dict[str, str]:
    """Display names for these tag values, for the ones that have one.

    Resolved through the runtime label store, so a name the crew set in the
    interface wins over the profile's. Imported locally because that store
    lives above this layer and reads the chat-history database.
    """
    from app.services import labels

    return labels.names_for(list(values), labels.LOCATION)


def case_variants(values: list[str]) -> dict[str, list[str]]:
    """Tag values differing only by capitalisation — e.g. AirLock / Airlock.

    These are separate tags in InfluxDB holding separate data, so a query for
    one silently misses the other. Surfacing them is how we avoid answering
    confidently from half the sensors.
    """
    buckets: dict[str, list[str]] = {}
    for value in values:
        buckets.setdefault(value.lower(), []).append(value)
    return {key: sorted(group) for key, group in buckets.items() if len(group) > 1}
