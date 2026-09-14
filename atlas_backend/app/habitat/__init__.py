"""The habitat profile — everything about THIS habitat that isn't discoverable.

A habitat's schema (measurements, tags, fields) is read from its database at
runtime. Three things cannot be: the units a number carries (InfluxDB 1.x
stores none), the human names for tag values (a tag reads `Container3`, the crew
say "dormitory"), and which tag keys name a place. Those, plus a display name,
are the habitat *profile*, and they live in a YAML file rather than in code so a
new analog mission configures ATLAS for its habitat without editing the source.

    from app.habitat import profile
    profile().name          # "My Habitat"
    profile().zone_names     # {"Container3": "Dormitory", ...}
    profile().unit_for(m, f) # ("°C", "known") | ("", "unknown")

The file is chosen by the `HABITAT_CONFIG` setting. There is no default
habitat: blank means no profile, so units read as unrecorded and the dashboard
is derived from the database. `config/examples/habitat.example.yaml` documents
every option. `app.telemetry.zones` and `app.telemetry.units` are thin views
over what is loaded here.
"""

from app.habitat.profile import HabitatProfile, profile, reset

__all__ = ["HabitatProfile", "profile", "reset"]
