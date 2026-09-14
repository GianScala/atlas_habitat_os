"""Binding tool names to the telemetry functions behind them.

The registry is the single seam between the model's vocabulary and the
telemetry package. Adding a capability means adding a function there, a schema
in schemas.py, and one line here.

NOT EVERY TELEMETRY FUNCTION IS A TOOL. `discovery` also exposes
list_measurements, list_locations and list_fields, and none of the three is
offered to the model: the measurement list is already in the prompt, and the
other two return subsets of what describe() returns in the same round. They
are still called from the API routes, which is where a list of measurements
actually has a reader. Left in the tool set they cost tokens on every request
and give the model three more ways to spend a round finding out something it
could have had in one.
"""

import json
from collections.abc import Callable
from typing import Any

from app.core.errors import AtlasError
from app.core.logging import get_logger
from app.habitat import profile
from app.knowledge.search import search_knowledge
from app.knowledge.store import connected_count
from app.mission.logquery import get_crew_meter_log
from app.mission.query import get_mission_plan
from app.telemetry import aggregation, availability, discovery, readings, tanks
from app.tools.schemas import TOOL_SCHEMAS

log = get_logger(__name__)

# Some tools only make sense for a habitat with a particular shape, so the tool
# set is driven by the habitat profile: a habitat with no tanks is not offered
# get_tank_flow, and one with no multi-phase meter is not offered
# get_latest_all_phases. Everything else is habitat-neutral and always offered.
# This is what lets a completely different mission get a coherent tool set from
# configuration alone. Each entry is a predicate over the active profile.
TOOL_REQUIRES: dict[str, "Callable[[], bool]"] = {
    "get_tank_flow": lambda: bool(profile().stock_measurements),
    "get_latest_all_phases": lambda: bool(profile().electrical),
    # The crew meter log is optional equipment: no declared dials, no second
    # account to read. Offering it to a habitat that keeps one account sends
    # per-room questions to a tool with nothing in it.
    "get_crew_meter_log": lambda: bool(profile().crew_log_meters),
    # Offered only once the crew has attached a document. A search tool over an
    # empty store is a round the model spends learning there is nothing there.
    "search_knowledge": lambda: connected_count() > 0,
}

TOOL_FUNCTIONS: dict[str, Callable[..., dict]] = {
    "find_measurements": discovery.find_measurements,
    "describe": discovery.describe,
    "get_latest": readings.get_latest,
    "get_history": readings.get_history,
    "get_latest_all_phases": readings.get_latest_all_phases,
    "time_range": readings.time_range,
    "summarize": aggregation.summarize,
    "get_consumption": aggregation.get_consumption,
    "get_tank_flow": tanks.get_tank_flow,
    "what_is_available": availability.what_is_available,
    # The two tools here that do not read the habitat's database.
    #
    # `get_mission_plan` reads the crew's plan, and the consumption measured
    # against it — the one thing no sensor knows.
    #
    # `get_crew_meter_log` reads the crew's own MEASUREMENTS: the sub-meter
    # dials they walk round and write down. It is a second, independent account
    # of water and power, and it is the only source in the system that knows
    # which room or which tap. Kept a separate tool from the telemetry ones on
    # purpose — see `mission/logquery.py`.
    "get_mission_plan": get_mission_plan,
    "get_crew_meter_log": get_crew_meter_log,
    # Not telemetry at all: the crew's own documents. See app/knowledge/.
    "search_knowledge": search_knowledge,
}


class ToolOutcome:
    """The result of one tool call, in both the shapes we need.

    `content` is the JSON text the model reads. `raw` is the parsed dict the
    API layer reads to build the provenance footer.
    """

    def __init__(self, name: str, content: str, is_error: bool, raw: dict[str, Any]):
        self.name = name
        self.content = content
        self.is_error = is_error
        self.raw = raw

    @property
    def queries(self) -> list[str]:
        """The queries this call actually ran, in the adapter's own dialect."""
        if self.is_error:
            return []
        found = self.raw.get("queries") or [self.raw.get("query")]
        return [q for q in found if q]


def _available(tool_name: str) -> bool:
    """Whether this tool applies to the active habitat."""
    predicate = TOOL_REQUIRES.get(tool_name)
    return predicate is None or predicate()


def schemas() -> list[dict]:
    """Tool definitions for the Messages API request.

    Tools that don't apply to this habitat (no tanks, no phased meter) are
    withheld, so the model is never offered a tool with nothing to answer.
    """
    return [s for s in TOOL_SCHEMAS if _available(s["name"])]


def run_tool(name: str, arguments: dict) -> ToolOutcome:
    """Run one tool and package its result.

    Failures come back as an outcome with is_error set rather than raising, so
    the model can recover and say what failed instead of the whole turn dying.
    """
    function = TOOL_FUNCTIONS.get(name)
    if function is None:
        return ToolOutcome(name, f"No such tool: {name}", True, {})
    if not _available(name):
        return ToolOutcome(
            name, f"{name} does not apply to this habitat.", True, {}
        )

    try:
        result = function(**arguments)
    except AtlasError as exc:
        log.warning("Tool %s failed: %s", name, exc.message)
        return ToolOutcome(name, f"Query failed: {exc.message}", True, {})
    except ValueError as exc:
        log.warning("Tool %s got bad arguments: %s", name, exc)
        return ToolOutcome(name, f"Query failed: {exc}", True, {})
    except TypeError as exc:
        log.warning("Tool %s called with wrong signature: %s", name, exc)
        return ToolOutcome(name, _signature_help(name, exc), True, {})

    return ToolOutcome(name, json.dumps(result, default=str), False, result)


def _signature_help(name: str, exc: TypeError) -> str:
    """A refusal the model can act on in one round instead of three.

    Python's own message names what is missing and stops there, which leaves a
    small model to work out the recovery for itself — and what it does is go
    looking: find_measurements, then describe, then the call it meant to make,
    three rounds and twenty seconds to supply one argument it was already
    holding. Naming the argument and where its value comes from turns that back
    into a single corrected call.
    """
    detail = str(exc)
    if "missing" in detail and "argument" in detail:
        return (
            f"{name} needs the {detail.split('argument')[-1].strip(': ')} argument. "
            "The measurement names are listed in your instructions, under 'What "
            "this habitat records' — take the name from there and call again now. "
            "Only search if none of them fits."
        )
    return f"Bad arguments for {name}: {detail}"
