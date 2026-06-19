"""Minimal ADK agent for the CX integration spike — one tool: ask_race_data.

This is the STUB the spike deploys (spec/cx_integration_spike.md, Path A step 1):
it reads Firestore "now", computes race_wall_time_ns, echoes it, and refuses a
future ("who wins?") question. No BigQuery yet. Its only job is to prove the
CX -> OpenAPI -> agent wire and the time-honesty behavior end to end.

The same agent core is what the real race_data_subagent build grows from; here
it deploys to Cloud Run and is served as a clean OpenAPI operation by app.py.
"""
from __future__ import annotations

import os

from now import is_future_question, read_now


def ask_race_data(question: str) -> dict:
    """Answer a race-data question, bounded to the replay's current moment.

    Stub behavior: reads "now", and either refuses (future question) or returns
    a canned answer that echoes the computed race_wall_time_ns so we can confirm
    the live moment flowed all the way through CX.

    Returns a dict (the OpenAPI route serializes it; the LLM agent reads it).
    """
    now = read_now()
    rt_s = now["race_time_s"]
    wall_ns = now["race_wall_time_ns"]

    if is_future_question(question):
        return {
            "answer": (
                "I can only speak to the race as it stands right now "
                f"(t+{rt_s:.0f}s) — I won't spoil what hasn't happened yet."
            ),
            "race_time_s": rt_s,
            "race_wall_time_ns": wall_ns,
            "now_source": now["source"],
            "refused_future": True,
        }

    return {
        "answer": (
            f"[stub] Read the live moment at race_time_s={rt_s:.0f} "
            f"(race_wall_time_ns={wall_ns}). The real subagent would now answer "
            f"\"{question}\" from Firestore/BigQuery bounded to this moment."
        ),
        "race_time_s": rt_s,
        "race_wall_time_ns": wall_ns,
        "now_source": now["source"],
        "refused_future": False,
    }


# ---------------------------------------------------------------------------
# The ADK agent. Used when the service runs in LLM mode (DETERMINISTIC=0).
# In DETERMINISTIC=1 mode (default for first-light), app.py calls ask_race_data
# directly and never invokes the model — a reliable wire test with no LLM creds.
# ---------------------------------------------------------------------------
MODEL = os.environ.get("FE_MODEL", "gemini-2.5-flash")

INSTRUCTION = """\
You answer Formula E race-data questions for a fan-facing concierge, bounded to
the replay's CURRENT moment.

ALWAYS call the `ask_race_data` tool with the user's question and return its
`answer` field. Never invent race facts. If the tool refuses (future/spoiler
question), relay that refusal as-is — you must never reveal what happens after
the current moment.
"""


def build_agent():
    """Construct the ADK agent. Imported lazily so DETERMINISTIC mode has no
    hard dependency on google-adk / Vertex creds being present."""
    from google.adk.agents import Agent

    return Agent(
        name="race_data_stub",
        model=MODEL,
        description=(
            "Spike stub: answers race-data questions bounded to the replay's "
            "current moment; refuses future/spoiler questions."
        ),
        instruction=INSTRUCTION,
        tools=[ask_race_data],
    )
