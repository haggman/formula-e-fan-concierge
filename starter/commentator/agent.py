"""Commentator agent (ADK) — STARTER. Stand up the broadcaster here.

This file is short on purpose. Almost everything is given; you wire the agent
together in ONE place (the TODO below).

What's already done for you:
  - the model and a sensible retry config (GIVEN, below);
  - your persona text, imported from prompts.py (that's YOUR build);
  - the four field-wide live tools, imported from tools/frame_tools.py (GIVEN
    infrastructure — they read the live race from Firestore).

Your job (Tier A, then C): construct `root_agent` so it uses your persona and
the four tools. The agent's job at runtime is to take a trigger prompt (with the
authoritative snapshot + the "fan is watching car N" line) and produce one
spoken commentary call.

`adk web` and the loop discover this module via __init__.py, which expects a
module-level `root_agent`.

Required env (exported by `source activate.sh`):
  GOOGLE_GENAI_USE_VERTEXAI=1
  GOOGLE_CLOUD_PROJECT=<lab project>
  GOOGLE_CLOUD_LOCATION=global
"""
from __future__ import annotations

import os

from google.adk.agents import Agent
from google.genai import types

# YOUR build — the persona you author in prompts.py:
from starter.commentator.prompts import (
    ROOT_AGENT_DESCRIPTION,
    ROOT_AGENT_INSTRUCTION,
)

# GIVEN infrastructure — the field-wide live tools (Firestore "now"). You don't
# need to read these; just register them on the agent so it can see the race.
from starter.commentator.tools.frame_tools import (
    get_field_state,
    get_recent_events,
    get_events_in_range,
    get_field_am_status,
)

# GIVEN — model knob and retry/backoff. Leave as-is.
MODEL = os.environ.get("FE_MODEL", "gemini-3.5-flash")

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

# ----------------------------------------------------------------------------
# TODO(student): build the agent.
#
# Construct an ADK Agent and assign it to `root_agent`. Pass:
#   name="commentator",
#   model=MODEL,
#   generate_content_config=shared_config,
#   description=ROOT_AGENT_DESCRIPTION,
#   instruction=ROOT_AGENT_INSTRUCTION,
#   tools=[get_field_state, get_recent_events, get_events_in_range,
#          get_field_am_status],
#
# Tier A tip: to SEE why grounding matters, first try it with tools=[] and an
# empty/partial persona — watch it invent positions. Then add your persona and
# the tools and watch it narrate the real race.
# ----------------------------------------------------------------------------

root_agent = None  # TODO(student): root_agent = Agent(...)
