"""Shapes for the preference endpoints.

Mirrored in `atlas_frontend/src/lib/types.ts`.
"""


from pydantic import BaseModel


class AssistantStyleOption(BaseModel):
    """One register on offer, as the settings page lists it."""

    key: str
    label: str
    blurb: str


class AssistantSettings(BaseModel):
    """The register in force, and what else is available."""

    # concise | detailed | unhinged | custom
    style: str
    # The crew's own instructions. Kept even while another style is selected,
    # so switching away and back does not lose what someone wrote.
    custom: str = ""
    options: list[AssistantStyleOption] = []


class StyleUpdate(BaseModel):
    """A change of register. `custom` is only read when style is 'custom'."""

    style: str
    custom: str | None = None
