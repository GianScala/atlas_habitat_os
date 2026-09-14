"""ATLAS - habitat telemetry assistant backend.

Layers, outermost first:

    api/         HTTP routing and dependency wiring
    services/    the agent loop, the system prompt, conversation state
    tools/       the tool surface the model sees
    telemetry/   habitat data access, in database-neutral terms
    datasource/  the adapters that speak to an actual habitat database
    schemas/     request, response, and event contracts
    core/        errors and logging

Each layer depends only on the ones beneath it.
"""

__version__ = "1.0.0"
