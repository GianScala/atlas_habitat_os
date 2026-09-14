"""Naming: what the crew calls the things the database names.

Two things live here, and they share a purpose — no habitat's nomenclature is
baked into ATLAS:

  /naming/labels  rename any measurement or location DISCOVERED in the database.
                  The habitat database is read-only and untouched; only the
                  display name changes.
  /naming/meters  add, rename, reorder or remove the dials on the crew's
                  hand-read meter round.
"""

from fastapi import APIRouter, HTTPException

from app.core.errors import AtlasError
from app.schemas.naming import (
    LabelCatalogue,
    LabelEntry,
    LabelUpdate,
    MeterRound,
    MeterSpecIn,
    MeterSpecOut,
    RoundUpdate,
)
from app.services import crew_meters, labels

router = APIRouter(prefix="/naming", tags=["naming"])


def _refuse(exc: AtlasError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


# -- display labels ---------------------------------------------------------


def _catalogue() -> LabelCatalogue:
    found = labels.catalogue()
    return LabelCatalogue(
        connected=found["connected"],
        detail=found["detail"],
        source=found["source"],
        measurements=[LabelEntry(**entry) for entry in found["measurements"]],
        locations=[LabelEntry(**entry) for entry in found["locations"]],
    )


@router.get("/labels", response_model=LabelCatalogue)
def read_labels() -> LabelCatalogue:
    """Everything renameable, read live from the habitat database."""
    try:
        return _catalogue()
    except AtlasError as exc:
        raise _refuse(exc) from exc


@router.put("/labels", response_model=LabelCatalogue)
def update_label(body: LabelUpdate) -> LabelCatalogue:
    """Rename one thing. An empty name restores whatever it was called before."""
    try:
        labels.set_label(body.kind, body.key, body.label or "")
        return _catalogue()
    except AtlasError as exc:
        raise _refuse(exc) from exc


@router.delete("/labels/{kind}/{key}", response_model=LabelCatalogue)
def clear_label(kind: str, key: str) -> LabelCatalogue:
    """Drop a crew name, falling back to the profile's or the raw tag."""
    try:
        labels.clear_label(kind, key)
        return _catalogue()
    except AtlasError as exc:
        raise _refuse(exc) from exc


# -- the crew's meter round -------------------------------------------------


def _round() -> MeterRound:
    current = crew_meters.meters()
    return MeterRound(
        customised=crew_meters.is_customised(),
        power=[_spec_out(spec) for spec in current[crew_meters.POWER]],
        water=[_spec_out(spec) for spec in current[crew_meters.WATER]],
    )


def _spec_out(spec) -> MeterSpecOut:
    return MeterSpecOut(
        key=spec.key,
        label=spec.label,
        code=spec.code,
        group=spec.group,
        group_label=spec.group_label,
        stream=spec.stream,
    )


@router.get("/meters", response_model=MeterRound)
def read_meters() -> MeterRound:
    """The dials on this habitat's round, in the order they are walked."""
    try:
        return _round()
    except AtlasError as exc:
        raise _refuse(exc) from exc


@router.put("/meters/{resource}", response_model=MeterRound)
def update_meters(resource: str, body: RoundUpdate) -> MeterRound:
    """Replace one resource's round with this list, in this order.

    Readings already logged are keyed by meter id, so renaming keeps a meter's
    history and removing one hides it rather than deleting anything.
    """
    try:
        crew_meters.save(resource, [entry.model_dump() for entry in body.meters])
        return _round()
    except AtlasError as exc:
        raise _refuse(exc) from exc


@router.post("/meters/reset", response_model=MeterRound)
def reset_meters() -> MeterRound:
    """Hand the round back to the habitat profile's list."""
    try:
        crew_meters.reset()
        return _round()
    except AtlasError as exc:
        raise _refuse(exc) from exc


__all__ = ["router", "MeterSpecIn"]
