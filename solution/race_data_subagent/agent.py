"""Race-data subagent (ADK) — reference solution.

Owns both worlds, time-honest:
  - now_tools       → Firestore live state (field-wide, any car)
  - ToolboxToolset  → BigQuery (R10 + 10-season career/results) via the deployed
    fe-toolbox MCP server (the same 14-tool curated set reused from Ch2)

Contract: read "now" first to learn the current moment, bound every BigQuery call
with through_time_ns = race_wall_time_ns from "now", and never answer about the
future. Enforced by the prompt (prompts.py) + the bound (now_tools derive
race_wall_time_ns from race_time_s via config, never the host clock).

Served to CX by app.py (get_fast_api_app() + a single POST /ask_race_data). The
agent IS the service — there is no separate wrapper. See README + spec.

INTERNAL IMPORTS ARE RELATIVE so this package is importable both as
`solution.race_data_subagent` (inside the repo) and as a top-level
`race_data_subagent` agent folder under an ADK agents_dir (in the Cloud Run
container — see app.py / Dockerfile). `shared.*` stays an absolute top-level
import (it's an installed package, copied alongside in the container).

Required env (set by activate.sh locally / the deploy script in the container):
GOOGLE_GENAI_USE_VERTEXAI=1, GOOGLE_CLOUD_PROJECT (or PROJECT_ID), TOOLBOX_URL
(deployed fe-toolbox). Optional: GOOGLE_CLOUD_LOCATION, FE_MODEL.
"""
from __future__ import annotations

import os

from google.adk.agents import Agent
from google.adk.tools.toolbox_toolset import ToolboxToolset
from google.genai import types

from .prompts import ROOT_AGENT_DESCRIPTION, ROOT_AGENT_INSTRUCTION
from .tools.now_tools import get_car_now, get_field_now, get_recent_events

MODEL = os.environ.get("FE_MODEL", "gemini-3.5-flash")

TOOLBOX_URL = os.environ.get("TOOLBOX_URL")
if not TOOLBOX_URL:
    raise RuntimeError(
        "TOOLBOX_URL required (deployed fe-toolbox). Run: source activate.sh "
        "(or set it in the Cloud Run deploy for the subagent)."
    )

# Reuse Ch2's curated BQ toolset verbatim — the 14-tool "race-engineer" set in
# toolbox/tools.yaml. The race tools cover R10; get_driver_career_stats +
# get_driver_info cover the 10-season career range.
toolbox_tools = ToolboxToolset(
    server_url=TOOLBOX_URL.rstrip("/"),
    toolset_name="race-engineer",
)

# Match the commentator's resilient generate config: shared-quota header + a
# bounded retry on the transient 4xx/5xx the live lab occasionally throws.
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
