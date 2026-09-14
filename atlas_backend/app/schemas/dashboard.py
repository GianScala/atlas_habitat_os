"""Shapes for the dashboard endpoints."""


from pydantic import BaseModel


class RangeOption(BaseModel):
    """A selectable window, for the range picker."""

    key: str
    label: str
    minutes: int
    bucket_minutes: int


class Point(BaseModel):
    t: str
    v: float


class PanelSeries(BaseModel):
    """One line on a chart."""

    key: str
    label: str
    points: list[Point] = []


class Panel(BaseModel):
    """One chart, with everything needed to draw and caption it."""

    id: str
    title: str
    subtitle: str
    group: str
    chart: str
    mode: str
    # Points are a running total across the window, not one bucket each.
    cumulative: bool = False
    unit: str = ""
    unit_source: str = "unknown"
    unit_note: str | None = None
    measurement: str
    field: str
    query: str = ""
    bucket_minutes: int = 0
    series: list[PanelSeries] = []
    # Set when this panel alone failed; the rest of the page still renders.
    error: str | None = None


class Dashboard(BaseModel):
    range: str
    range_label: str
    panels: list[Panel] = []
