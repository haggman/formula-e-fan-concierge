"""Commentator agent (ADK) — pure wiring. [SKELETON]

Re-aim of Ch2's race_engineer/agent.py. Differences:
  - NO ToolboxToolset: the commentator narrates the live field, it does not
    query BigQuery history. (Stats questions belong to the CX concierge and
    its race-data subagent.)
  - Tools are the FIELD-WIDE frame tools (see tools/frame_tools.py), which take
    an optional `selected_car` so commentary can narrow focus.

Implementation deferred to the build conversation; this file fixes the shape.
`adk web` discovers this module via solution/commentator/__init__.py.

Required env (exported by `source activate.sh`):
  GOOGLE_GENAI_USE_VERTEXAI=1
  GOOGLE_CLOUD_PROJECT=<lab project>
  GOOGLE_CLOUD_LOCATION=global
"""
from __future__ import annotations

import os

from google.adk.agents import Agent
from google.genai import types

from solution.commentator.prompts import (
    ROOT_AGENT_DESCRIPTION,
    ROOT_AGENT_INSTRUCTION,
)
from solution.commentator.tools.frame_tools import (
    get_field_state,
    get_recent_events,
    get_events_in_range,
    get_field_am_status,
)

MODEL = os.environ.get("FE_MODEL", "gemini-3.5-flash")

# Retry/backoff config — kept from Ch2 (the trigger loop owns higher-level
# retry semantics; fail fast per LLM step).
shared_config = types.GenerateContentConfig(
    http_options=types.HttpOptions(
        api_version="v1",
        headers={"X-Vertex-AI-LLM-Request-Type": "shared"},
        retry_options=types.HttpRetryOptions(
            attempts=4,
            initial_delay=0.5,
            max_delay=4.0,
            exp_base=2.0,
            jitter=1.0,
            http_status_codes=[408, 429, 500, 502, 503, 504],
        ),
    ),
)

root_agent = Agent(
    name="commentator",
    model=MODEL,
    generate_content_config=shared_config,
    description=ROOT_AGENT_DESCRIPTION,
    instruction=ROOT_AGENT_INSTRUCTION,
    tools=[
        get_field_state,
        get_recent_events,
        get_events_in_range,
        get_field_am_status,
    ],
)
