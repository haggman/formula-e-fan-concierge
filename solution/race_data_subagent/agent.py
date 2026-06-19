"""Race-data subagent (ADK) — pure wiring. [SKELETON]

Owns both worlds, time-honest:
  - now_tools  → Firestore live state (field-wide)
  - ToolboxToolset → BigQuery (R10 + 10-season career/results) via the deployed
    fe-toolbox MCP server (reused from Ch2)

The agent's contract: read "now" first to learn the current moment, bound every
BQ call with through_time_ns = race_time_to_wall_ns(current race_time_s), and
never answer about the future. Enforced by prompt + the bound; see README.

Wrapped for CX by mcp_server.py (one tool: ask_race_data).

Required env (via activate.sh): GOOGLE_GENAI_USE_VERTEXAI=1, GOOGLE_CLOUD_PROJECT,
GOOGLE_CLOUD_LOCATION=global, TOOLBOX_URL (deployed fe-toolbox).
"""
from __future__ import annotations

import os

from google.adk.agents import Agent
from google.adk.tools.toolbox_toolset import ToolboxToolset
from google.genai import types

from solution.race_data_subagent.prompts import (
    ROOT_AGENT_DESCRIPTION,
    ROOT_AGENT_INSTRUCTION,
)
from solution.race_data_subagent.tools.now_tools import (
    get_car_now,
    get_field_now,
    get_recent_events,
)

MODEL = os.environ.get("FE_MODEL", "gemini-3.5-flash")

TOOLBOX_URL = os.environ.get("TOOLBOX_URL")
if not TOOLBOX_URL:
    raise RuntimeError("TOOLBOX_URL required (deployed fe-toolbox). Run: source activate.sh")

# Reuse Ch2's curated BQ toolset. The race tools map near-directly; career tools
# (get_driver_career_stats, etc.) cover the 10-season range.
toolbox_tools = ToolboxToolset(
    server_url=TOOLBOX_URL.rstrip("/"),
    toolset_name="race-engineer",  # same curated set; rename if we cut/extend
)

shared_config = types.GenerateContentConfig(
    http_options=types.HttpOptions(
        api_version="v1",
        headers={"X-Vertex-AI-LLM-Request-Type": "shared"},
        retry_options=types.HttpRetryOptions(
            attempts=4, initial_delay=0.5, max_delay=4.0, exp_base=2.0,
            jitter=1.0, http_status_codes=[408, 429, 500, 502, 503, 504],
        ),
    ),
)

root_agent = Agent(
    name="race_data_subagent",
    model=MODEL,
    generate_content_config=shared_config,
    description=ROOT_AGENT_DESCRIPTION,
    instruction=ROOT_AGENT_INSTRUCTION,
    tools=[
        get_field_now,
        get_car_now,
        get_recent_events,
        toolbox_tools,
    ],
)
