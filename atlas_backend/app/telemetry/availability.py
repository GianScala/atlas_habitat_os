"""What is actually live right now.

Discovery says what EXISTS; this says what currently RETURNS a reading. The
distinction matters in a habitat: a measurement can be defined and its sensor
silent, and reporting the first as if it were the second is misleading.

Deliberately empirical, and slow — it probes every measurement/location pair.
"""


from app.core.errors import AtlasError
from app.telemetry.discovery import (
    default_field,
    default_location_key,
    discover,
    tag_values,
)
from app.telemetry.readings import get_latest
from app.telemetry.units import unit_for


def _display(location: str) -> str:
    """The crew-facing name for a location. Local import: see zones.py."""
    from app.services import labels

    return labels.display_name(location, labels.LOCATION)


def what_is_available(measurements: list[str] | None = None) -> dict:
    """Which measurement/location pairs return a reading right now.

    Probes every habitat measurement unless given a shorter list.
    """
    targets = measurements or discover()["habitat"]

    live: dict[str, list[dict]] = {}
    silent: dict[str, list[str]] = {}
    failed: dict[str, str] = {}

    for measurement in targets:
        try:
            _probe(measurement, live, silent)
        except (AtlasError, ValueError) as exc:
            failed[measurement] = str(exc)[:160]

    return {
        "query": "probe of every discovered habitat measurement/location pair",
        "data": live or None,
        "no_data_for": silent,
        "could_not_probe": failed,
    }


def _probe(
    measurement: str,
    live: dict[str, list[dict]],
    silent: dict[str, list[str]],
) -> None:
    """Probe one measurement, recording it as live or silent."""
    location_key = default_location_key(measurement)
    field = default_field(measurement)
    unit, _ = unit_for(measurement, field)

    if location_key is None:
        reading = get_latest(measurement, field=field)
        if reading["data"]:
            live[measurement] = [
                {
                    "location": None,
                    "value": reading["data"]["value"],
                    "time": reading["data"]["time"],
                    "unit": unit,
                }
            ]
        else:
            silent[measurement] = []
        return

    here: list[dict] = []
    quiet: list[str] = []

    for location in tag_values(measurement, location_key):
        reading = get_latest(measurement, location=location, field=field)
        if reading["data"] is None:
            quiet.append(location)
        else:
            here.append(
                {
                    "location": location,
                    "zone_name": _display(location),
                    "value": reading["data"]["value"],
                    "time": reading["data"]["time"],
                    "unit": unit,
                }
            )

    if here:
        live[measurement] = here
    if quiet:
        silent[measurement] = quiet
