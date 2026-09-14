"""Tool schemas as the model sees them.

No measurement, location, or field is hardcoded here — the model discovers
them at runtime.

WHAT A DESCRIPTION IS FOR, AND WHAT IT IS NOT FOR. It says what this tool
returns and what distinguishes it from its neighbours. It does NOT restate the
operational judgement in `services/prompt.py` — which of the three kinds of
number a field is, when to omit `days`, when a fall is consumption and when a
rise is. Those rules are in the system prompt, stated once.

That division is a performance constraint, not a matter of taste. Every schema
here is re-sent on every round of every turn, so the whole set is part of the
fixed prefix the model must read before it looks at the question. On the local
runtime that prefix is prefilled at roughly 120 tokens/second whenever the KV
cache misses, which puts a straight price on every repeated sentence: this file
grew to 4,450 tokens once, and the duplication alone cost about twenty seconds
of silence per question. Say it in the prompt or say it here, not in both.
"""

# THESE ARE THE EXPENSIVE ONES. A shared parameter is re-serialised into every
# tool that uses it, so the count after the `x` below is a multiplier on every
# word: FIELD is six tools' worth. Their full rules are in the system prompt's
# "Tags and locations" section, stated once and paid for once.

MEASUREMENT = {  # x7
    "type": "string",
    "description": (
        "REQUIRED. Case-sensitive, from 'What this habitat records' above."
    ),
}

LOCATION = {  # x6
    "type": "string",
    "description": (
        "Place tag value, as the database spells it. The habitat's zone names "
        "are listed in your instructions. Omit to cover all locations."
    ),
}

FIELD = {  # x6
    "type": "string",
    "description": "OMIT unless you have seen this measurement's real field names.",
}

TAGS = {  # x5
    "type": "object",
    "description": 'Exact tag filters beyond location, e.g. {"Sensor": "BME280"}.',
    "additionalProperties": {"type": "string"},
}

GROUP_BY = {
    "type": "string",
    "enum": ["hour", "day", "week"],
    "description": "Bucket size for the per-period breakdown. Defaults to day.",
}

START = {
    "type": "string",
    "description": "Exact ISO 8601 start instant, e.g. '2026-08-18T05:00:00Z'. UTC.",
}

END = {
    "type": "string",
    "description": "Exact ISO 8601 end instant. Omit to run up to now.",
}

PHASE = {
    "type": "string",
    "description": (
        "Phase of a multi-phase electrical meter, where the habitat has one. "
        "Only meaningful on the phased measurement named in your instructions."
    ),
}

DAYS = {  # x3
    "type": "number",
    "description": "Rolling window back from now, in days. OMIT to cover all history.",
}


TOOL_SCHEMAS: list[dict] = [
    {
        "name": "find_measurements",
        "description": (
            "Search EVERY measurement's name, field keys, and tag keys for a "
            "keyword. This is how you find out whether the habitat records "
            "something, and where. The same physical quantity is often "
            "recorded twice under different names — a whole-habitat meter and "
            "per-room submeters, say — so a search for 'power' or 'water' can "
            "legitimately return several measurements. Read what each is "
            "tagged by before choosing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": (
                        "Concept to search for, e.g. 'power' or 'co2'. Matched "
                        "case-insensitively as a substring."
                    ),
                }
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "describe",
        "description": (
            "Report a measurement's real tag keys, tag values, and field keys, "
            "with units where known. Also flags tag values that differ only by "
            "capitalisation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"measurement": MEASUREMENT},
            "required": ["measurement"],
        },
    },
    {
        "name": "get_latest",
        "description": (
            "The most recent reading for a measurement, optionally at one "
            "location. The tool for 'what is X right now'. Returns value, "
            "unit, and the ISO timestamp of that reading, or data=null if "
            "nothing has been recorded for that combination."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "measurement": MEASUREMENT,
                "location": LOCATION,
                "field": FIELD,
                "phase": PHASE,
                "tags": TAGS,
            },
            "required": ["measurement"],
        },
    },
    {
        "name": "get_history",
        "description": (
            "Time-bucketed mean over the last N MINUTES — for short-term "
            "trends ('is it warming up', 'what has it done this hour'). For "
            "windows of days, use summarize instead."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "measurement": MEASUREMENT,
                "location": LOCATION,
                "field": FIELD,
                "minutes": {"type": "integer", "description": "Defaults to 60."},
                "tags": TAGS,
            },
            "required": ["measurement"],
        },
    },
    {
        "name": "summarize",
        "description": (
            "KIND 1, rates and levels at an instant. Statistics over a window "
            "of days, bucketed by hour/day/week: mean, min, max and sample "
            "count per period, plus an overall figure."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "measurement": MEASUREMENT,
                "location": LOCATION,
                "field": FIELD,
                "days": DAYS,
                "group_by": GROUP_BY,
                "phase": PHASE,
                "tags": TAGS,
                "start": START,
                "end": END,
            },
            "required": ["measurement"],
        },
    },
    {
        "name": "get_consumption",
        "description": (
            "KIND 2, cumulative totalisers. How much was USED over a window: "
            "last minus first per period, with both endpoints returned so the "
            "arithmetic is checkable, plus the whole-window total and the "
            "average per period. Broken out PER SERIES and then summed, since "
            "three electrical phases each keep their own totaliser. Verifies "
            "the field really does climb, and returns cumulative=false with a "
            "`redirect` instead of a total if it ever drops."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "measurement": MEASUREMENT,
                "field": FIELD,
                "location": LOCATION,
                "days": DAYS,
                "group_by": GROUP_BY,
                "phase": PHASE,
                "tags": TAGS,
                "start": START,
                "end": END,
            },
            "required": ["measurement"],
        },
    },
    {
        "name": "get_tank_flow",
        "description": (
            "KIND 3, stocks — water tanks above all. How much the level fell "
            "and how much it rose, reported separately and never netted: "
            "per-period `fell` and `rose`, whole-window totals, per-day rates, "
            "and the opening and closing levels. The tool for any 'how much "
            "water did we use' question, and for whatever get_consumption "
            "redirects here. Movements below the gauge's measured noise floor "
            "are discarded; the deadband used and its source are returned."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "measurement": MEASUREMENT,
                "field": FIELD,
                "location": LOCATION,
                "tags": {
                    "type": "object",
                    "description": (
                        "Exact tag filters naming ONE tank, as describe() "
                        "reports them. Omit to decompose every tank the "
                        "measurement covers, each on its own."
                    ),
                    "additionalProperties": {"type": "string"},
                },
                "days": DAYS,
                "group_by": GROUP_BY,
                "start": START,
                "end": END,
                "deadband": {
                    "type": "number",
                    "description": (
                        "Smallest movement to count, in the field's own units. "
                        "OMIT — the instrument's measured noise floor is used, "
                        "and a guessed threshold either invents use or erases "
                        "it."
                    ),
                },
            },
            "required": ["measurement"],
        },
    },
    {
        "name": "get_latest_all_phases",
        "description": (
            "Latest reading on every phase of the habitat's multi-phase "
            "electrical meter, plus their sum — for total instantaneous draw. "
            "Which measurement and phases those are is configured for this "
            "habitat. Phases with no data are listed and excluded rather than "
            "assumed zero. Warns when summing a field where a sum is not "
            "physically meaningful (voltage, frequency)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "field": {
                    "type": "string",
                    "description": (
                        "Which electrical field to read on every phase. Omit "
                        "for this habitat's default; call describe() on the "
                        "phased measurement to see the real field names."
                    ),
                }
            },
            "required": ["field"],
        },
    },
    {
        "name": "time_range",
        "description": (
            "The timestamps of the oldest and newest readings on record for a "
            "measurement — how much history actually exists."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "measurement": MEASUREMENT,
                "field": FIELD,
                "location": LOCATION,
                "tags": TAGS,
            },
            "required": ["measurement"],
        },
    },
    {
        "name": "what_is_available",
        "description": (
            "Probe every discovered measurement and location and report which "
            "currently return a reading and which are silent. For 'what can "
            "you tell me about'. Runs many queries and is SLOW — never use it "
            "for a question about one specific sensor."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "measurements": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional subset to probe, to keep it fast.",
                }
            },
        },
    },
    {
        "name": "search_knowledge",
        "description": (
            "Search the documents the crew has attached: procedures, emergency "
            "contact sheets, checklists, manuals. Use this for any question "
            "that is not a sensor reading — how to do something, who to call, "
            "what a limit is, what the protocol says. Returns passages with the "
            "document they came from. Quote them and name the document; if they "
            "do not answer the question, say so rather than filling the gap."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "What to look for, in the words the document would use. "
                        "A phrase works better than a single word."
                    ),
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_mission_plan",
        "description": (
            "The crew's mission plan and how consumption is tracking against "
            "it — budgets, allowances, targets, whether the habitat is on "
            "plan, how much is left, what a day should cost. Returns: the "
            "mission's dates and which mission day today is (MD-01, MD-02...); "
            "each resource's ceiling over the whole mission; the allowance for "
            "a single day, a 3-day cycle, and the mission, each against what "
            "the meters actually recorded; the extras booked onto particular "
            "days; and the REVISED daily allowance, what a day may cost from "
            "now on to still finish inside the ceiling. Says so plainly if no "
            "mission has been declared."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "resource": {
                    "type": "string",
                    "enum": ["water", "power"],
                    "description": "Limit to one resource. Omit to get both.",
                }
            },
            "required": [],
        },
    },
    {
        "name": "get_crew_meter_log",
        "description": (
            "Power PER ROOM and water PER TAP, from sub-meter dials the crew "
            "reads by hand. THE ONLY SOURCE THAT KNOWS WHICH ROOM OR WHICH "
            "TAP — the database meters the mains and the clean-water feed "
            "only, so no query can break either down by place. Use it for "
            "'which room uses the most power', 'how much water does the "
            "shower take', 'warm vs cold', 'is the kitchen heavy'. Rooms: "
            "Kitchen, Dormitory, Operations, Gym, Analytic Lab, Bio Lab, "
            "Hygiene. Taps: toilet 1B, toilet sink 2R/2B, shower-room sink "
            "3R/3B, shower 4R/4B, laundry 5B, second shower 6R/6B, kitchen "
            "7B (R is warm, B is cold). Returns totals and shares for the "
            "latest logged day, the last 3, and the whole mission, plus a "
            "per-day series and what the record is missing. Power in kWh, "
            "water in LITRES. This is a SEPARATE ACCOUNT from the telemetry "
            "tools: never add the two together or average them."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "resource": {
                    "type": "string",
                    "enum": ["water", "power"],
                    "description": "Limit to one. Omit to get both.",
                },
                "meter": {
                    "type": "string",
                    "description": (
                        "One room or tap, by name or pipe code — 'Kitchen', "
                        "'4R'. Omit for all of them."
                    ),
                },
                "mission_day": {
                    "type": "integer",
                    "description": (
                        "One mission day (1 is MD-01), broken out block by "
                        "block. Omit for the summary."
                    ),
                },
            },
            "required": [],
        },
    },
]
