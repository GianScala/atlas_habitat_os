"""Shapes for the Naming page: display names, and the crew's meter round."""

from typing import Literal

from pydantic import BaseModel, Field


class LabelEntry(BaseModel):
    """One renameable thing, as the database spells it and as the crew reads it."""

    #: The value in the database. Queries use this; it is never changed.
    key: str
    #: What the interface shows.
    label: str
    #: crew | profile | raw — where the display name came from.
    source: str
    #: For a location: which measurements report it. Empty for a measurement.
    seen_in: list[str] = Field(default_factory=list)


class LabelCatalogue(BaseModel):
    """What the connected database holds, and what each thing is called here."""

    #: False when no database could be read. The lists are then empty because
    #: nothing is loaded, not because the habitat has no sensors.
    connected: bool = True
    #: Why nothing could be read, when nothing could.
    detail: str | None = None
    #: Which data source answered, for the page to name.
    source: str = ""
    measurements: list[LabelEntry]
    locations: list[LabelEntry]


class LabelUpdate(BaseModel):
    kind: Literal["location", "measurement"]
    key: str
    #: Empty restores the profile's name, or the raw value.
    label: str = ""


class MeterSpecIn(BaseModel):
    """One dial, as the crew describes it."""

    #: Stable id. Readings are keyed by it, so keep it when renaming. Generated
    #: from the label when a new meter is added without one.
    key: str = ""
    label: str
    #: What is stencilled on the pipe or panel, for finding it at the wall.
    code: str = ""
    group: str = ""
    group_label: str = ""
    stream: Literal["warm", "cold", "none"] = "none"


class MeterSpecOut(MeterSpecIn):
    key: str


class RoundUpdate(BaseModel):
    """A resource's whole round, in the order it is walked."""

    meters: list[MeterSpecIn]


class MeterRound(BaseModel):
    """The dials in force, and whether the crew has taken them over."""

    #: True once the crew has edited the round; false while the profile's stands.
    customised: bool
    power: list[MeterSpecOut]
    water: list[MeterSpecOut]
