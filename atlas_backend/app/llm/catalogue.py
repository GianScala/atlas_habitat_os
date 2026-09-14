"""The models offered on the Models page.

A short, opinionated list rather than the whole Ollama library: these are the
sizes that fit on a laptop and, with one deliberate exception, the ones that
can actually call the telemetry tools. Anything else can still be installed by
name — the catalogue is a starting point, not a fence.

WHY TOOL SUPPORT IS THE FIRST THING SAID ABOUT EACH ONE. ATLAS answers by
querying InfluxDB, and a model that cannot call a tool cannot query anything.
It will still write a fluent, confident, entirely invented answer. So a model
without tool support is a different product, and the page says so before it
is installed rather than after.

The flags here are expectations. Once a model is on disk, Ollama reports what
it can really do and that measurement replaces the guess — see `inventory.py`.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CatalogueEntry:
    """One offered model."""

    name: str
    description: str
    #: Download size, as Ollama reports it for the default quantisation.
    size_note: str
    #: One word shown beside the name: recommended, reasoning, lightweight.
    badge: str = ""
    #: Expected to be able to call tools.
    tools: bool = True
    #: Expected to reason visibly before answering.
    thinks: bool = False


CATALOGUE: list[CatalogueEntry] = [
    CatalogueEntry(
        name="qwen3.5:9b",
        description=(
            "The default choice for ATLAS. Strong reasoning and reliable tool "
            "use while still being practical on a laptop. The best balance of "
            "quality, speed, and memory use for a 16 GB Mac."
        ),
        size_note="~6.6 GB",
        badge="recommended",
        tools=True,
        thinks=True,
    ),

    CatalogueEntry(
        name="qwen3.5:4b",
        description=(
            "The fast option. Much lighter than the 9B while retaining useful "
            "reasoning and native tool support. Best when responsiveness matters "
            "more than handling difficult multi-step questions."
        ),
        size_note="~3.4 GB",
        badge="lightweight",
        tools=True,
        thinks=True,
    ),

    CatalogueEntry(
        name="ministral-3:8b",
        description=(
            "Mistral's newer edge model. Strong instruction following, multilingual "
            "performance, and native function calling. A fast alternative to Qwen "
            "for telemetry and agent-style workflows."
        ),
        size_note="~6.0 GB",
        tools=True,
        thinks=False,
    ),

    CatalogueEntry(
        name="qwen3.5:27b",
        description=(
            "The high-quality local option. Significantly stronger reasoning and "
            "judgement than the smaller models, but too memory-heavy for most "
            "16 GB laptops. Best suited to Macs with 32 GB or more unified memory."
        ),
        size_note="~17 GB",
        badge="reasoning",
        tools=True,
        thinks=True,
    ),
]

BY_NAME = {entry.name: entry for entry in CATALOGUE}


def canonical(name: str) -> str:
    """A model name with Ollama's implied tag made explicit and then dropped.

    `ollama pull mistral-nemo` lands on disk as `mistral-nemo:latest`. The two
    are one model, and a page that listed both would be lying about how much
    disk is in use. A tag that is not `latest` is part of the identity —
    `qwen3:8b` and `qwen3:32b` are different downloads.
    """
    trimmed = name.strip()
    return trimmed[: -len(":latest")] if trimmed.endswith(":latest") else trimmed


def find(name: str) -> CatalogueEntry | None:
    """The catalogue entry for a model name, or None if it is not one of ours."""
    return BY_NAME.get(canonical(name))
