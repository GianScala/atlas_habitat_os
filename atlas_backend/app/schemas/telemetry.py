"""Shapes for the metadata endpoints the frontend reads at startup."""


from pydantic import BaseModel


class HealthStatus(BaseModel):
    """Whether the two things ATLAS depends on are actually reachable.

    Two, still, but one of them has moved: the model used to be a key in a
    file, and is now a process that may or may not be running on this machine.
    So `model_ready` is a real check rather than a configuration read.
    """

    status: str
    model: str
    provider: str = ""
    model_label: str = ""
    #: True when answering a question sends nothing off the machine.
    local: bool = False
    #: True when the selected data-source adapter has what it needs to connect.
    datasource_configured: bool
    #: The chosen model could answer a question right now.
    model_ready: bool = False
    #: Why not, when it could not.
    model_detail: str | None = None
    datasource_ok: bool | None = None
    datasource_detail: str | None = None
    measurement_count: int | None = None


class ZoneInfo(BaseModel):
    tag: str
    name: str


class MeasurementList(BaseModel):
    """What the habitat monitors, discovered live."""

    measurements: list[str]
    count: int
    note: str | None = None


class SuggestedQuestion(BaseModel):
    """A starter question shown on the empty chat screen."""

    label: str
    question: str
