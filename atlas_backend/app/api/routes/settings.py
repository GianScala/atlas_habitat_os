"""Preferences that change how ATLAS behaves, but not what it may say.

At present one: the register answers are written in. It lives here rather than
under /models because it is not a property of any model — switching from a
local model to the cloud must not silently change how the crew is spoken to.
"""

from fastapi import APIRouter, HTTPException

from app.core.errors import AtlasError
from app.schemas.settings import AssistantSettings, AssistantStyleOption, StyleUpdate
from app.services import style as st

router = APIRouter(prefix="/settings", tags=["settings"])


def _snapshot() -> AssistantSettings:
    choice = st.active()
    return AssistantSettings(
        style=choice.key,
        custom=choice.custom,
        options=[
            AssistantStyleOption(key=option.key, label=option.label, blurb=option.blurb)
            for option in st.available()
        ],
    )


@router.get("/assistant", response_model=AssistantSettings)
def read_assistant() -> AssistantSettings:
    """The register in force, and the ones on offer."""
    return _snapshot()


@router.put("/assistant", response_model=AssistantSettings)
def update_assistant(body: StyleUpdate) -> AssistantSettings:
    """Answer in this register from now on.

    Takes effect on the next question — the prompt is assembled per turn, so
    there is no cache to clear and no restart to do.
    """
    try:
        st.choose(body.style, body.custom)
        return _snapshot()
    except AtlasError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
