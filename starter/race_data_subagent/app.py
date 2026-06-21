"""Cloud Run service for the race-data subagent — the agent IS the service.

Decided in the CX integration spike (spec/cx_integration_spike.md) and validated
live 2026-06-19: the ADK agent runs on Cloud Run and serves its own clean
OpenAPI operation — CX's OpenAPI tool calls POST /ask_race_data directly. There
is NO separate wrapper/facade. (Agent Engine cannot expose a custom OpenAPI
path; A2A/Agent Registry aren't consumable by CX today. See the spec.)

Two modes, chosen by the DETERMINISTIC env var:

  DETERMINISTIC=1 (first-light, default) — POST /ask_race_data answers
      deterministically: read "now", refuse a future/spoiler question, else echo
      the computed race_wall_time_ns. NO LLM, NO Vertex creds, NO Toolbox needed
      — a reliable wire + time-honesty test, and the path the local verification
      harness exercises. The app is a plain FastAPI instance.

  DETERMINISTIC=0 (the real subagent) — the app IS ADK's get_fast_api_app()
      (canonical "ADK agent on Cloud Run"; auto-serves /openapi.json and the
      /run* + session endpoints), and POST /ask_race_data runs the real
      LlmAgent (Firestore "now" + BigQuery "then", time-honest) via a Runner.

Either way the single CX-facing operation is POST /ask_race_data {question} ->
{answer, ...}. The serving layer differs only in what builds `app`; see README
("Serving layer") for the rationale and how to flip it.

Optional A2A door (A2A_ENABLED=1): mounts the agent's A2A app at /a2a for the
Agent Registry / agent-to-agent showcase. A2A is JSON-RPC + agent-card, NOT
OpenAPI — it does not serve CX. Off the critical path.

Run locally:   DETERMINISTIC=1 uvicorn app:app --port 8080
Container:      uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}   (see Dockerfile)
"""
from __future__ import annotations

import logging
import os
import sys
import uuid

from fastapi import FastAPI
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("race_data_subagent")

DETERMINISTIC = os.environ.get("DETERMINISTIC", "1") == "1"
APP_NAME = "race_data_subagent"

# ---------------------------------------------------------------------------
# Make the agent package importable as the top-level `race_data_subagent`.
#
# get_fast_api_app(agents_dir=AGENTS_DIR) inserts AGENTS_DIR on sys.path and
# imports each subfolder as a top-level agent package; our package uses relative
# internal imports so it loads cleanly that way. `shared.*` (imported by
# now_tools) resolves from this file's own directory (WORKDIR on Cloud Run).
#
# Container layout (see Dockerfile):  /app/app.py · /app/agents/race_data_subagent
#                                     /app/shared
# Default AGENTS_DIR = <dir of app.py>/agents; override with ADK_AGENTS_DIR.
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
AGENTS_DIR = os.environ.get("ADK_AGENTS_DIR", os.path.join(_HERE, "agents"))
for _p in (_HERE, AGENTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Time-honesty helpers — import-light (lazy Firestore inside), so the
# DETERMINISTIC path needs neither google-adk nor firestore to load.
from race_data_subagent.tools.now_tools import (  # noqa: E402
    is_future_question,
    read_now,
)


# ---------------------------------------------------------------------------
# Request / response contract (matches openapi_ask_race_data.yaml).
# ---------------------------------------------------------------------------
class AskRequest(BaseModel):
    question: str = Field(..., description="The fan's race-data question.")


class AskResponse(BaseModel):
    answer: str = Field(..., description="The answer, bounded to the current moment.")
    race_time_s: int = Field(..., description="Replay seconds since green flag.")
    race_wall_time_ns: int = Field(..., description="Computed 2024 wall-clock ns of 'now'.")
    now_source: str = Field(..., description="'firestore' (live) or 'canned' (fallback).")
    refused_future: bool = Field(..., description="True if a future/spoiler question was refused.")
    mode: str = Field(..., description="'deterministic', 'llm', or 'llm-error'.")
    error: str | None = Field(None, description="Set only when the agent run failed (mode='llm-error').")


# ---------------------------------------------------------------------------
# Deterministic answer (no LLM) — proves the wire + time-honesty with no creds.
# ---------------------------------------------------------------------------
def deterministic_answer(question: str) -> dict:
    now = read_now()
    rt_s = now["race_time_s"]
    base = {
        "race_time_s": rt_s,
        "race_wall_time_ns": now["race_wall_time_ns"],
        "now_source": now["now_source"],
        "mode": "deterministic",
    }
    if is_future_question(question):
        return {
            **base,
            "answer": (
                "I can only speak to the race as it stands right now "
                f"(t+{rt_s}s) — I won't spoil what hasn't happened yet."
            ),
            "refused_future": True,
        }
    return {
        **base,
        "answer": (
            f"[deterministic] Read the live moment at race_time_s={rt_s} "
            f"(race_wall_time_ns={now['race_wall_time_ns']}). The LLM subagent "
            f"would now answer \"{question}\" from Firestore/BigQuery bounded to "
            "this moment."
        ),
        "refused_future": False,
    }


# ---------------------------------------------------------------------------
# Build `app`. In LLM mode it IS get_fast_api_app(); in deterministic mode it's
# a plain FastAPI instance (so first-light needs no google-adk / Vertex / Toolbox).
# ---------------------------------------------------------------------------
if DETERMINISTIC:
    app = FastAPI(
        title="Race-Data Subagent",
        version="1.0.0",
        description="ADK race-data subagent (deterministic first-light mode).",
    )
else:
    from google.adk.cli.fast_api import get_fast_api_app  # noqa: E402

    app = get_fast_api_app(
        agents_dir=AGENTS_DIR,
        web=os.environ.get("ADK_WEB_UI", "0") == "1",
        allow_origins=["*"],
    )


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "deterministic": DETERMINISTIC}


# ---- LLM mode: lazy Runner singleton (one process, one event loop). ----------
_runner = None
_session_service = None


async def _run_llm(question: str) -> dict:
    """Run the real ADK agent once; return the now-tool structured fields plus
    the model's final text as `answer`."""
    global _runner, _session_service
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    from race_data_subagent.agent import root_agent

    if _runner is None:
        _session_service = InMemorySessionService()
        _runner = Runner(
            agent=root_agent, app_name=APP_NAME, session_service=_session_service
        )

    # Unique per-request session id — a FIXED id throws AlreadyExistsError on the
    # 2nd+ request to a warm instance (the spike's "tool test works, agent call
    # fails" bug). See KNOWN_FIXES.md.
    uid, sid = "cx", f"cx-{uuid.uuid4().hex}"
    await _session_service.create_session(app_name=APP_NAME, user_id=uid, session_id=sid)

    now_fields: dict | None = None
    final_text = ""
    msg = types.Content(role="user", parts=[types.Part(text=question)])
    async for event in _runner.run_async(user_id=uid, session_id=sid, new_message=msg):
        for fr in event.get_function_responses() or []:
            if fr.name in ("get_field_now", "get_car_now", "get_recent_events"):
                resp = fr.response
                if isinstance(resp, dict):
                    now_fields = resp.get("result", resp)
        if event.is_final_response() and event.content and event.content.parts:
            final_text = (event.content.parts[0].text or "").strip()

    # Guarantee the time-honest fields even if the model answered without a now
    # tool (the prompt says always call one first; this is the backstop).
    now_fields = now_fields or read_now()
    return {
        "answer": final_text or "(no answer)",
        "race_time_s": int(now_fields.get("race_time_s", 0)),
        "race_wall_time_ns": int(now_fields.get("race_wall_time_ns", 0)),
        "now_source": now_fields.get("now_source", "unknown"),
        "refused_future": is_future_question(question),
        "mode": "llm",
    }


def _error_answer(question: str, exc: Exception) -> dict:
    """Always return valid JSON, even when the agent run blows up. The full
    traceback goes to Cloud Run logs (logger.exception below); CX gets a safe,
    grounded-failure answer rather than an empty body / 500. mode='llm-error' is
    the tell in the response that something failed."""
    try:
        now = read_now()
    except Exception:  # noqa: BLE001
        now = {"race_time_s": 0, "race_wall_time_ns": 0, "now_source": "unavailable"}
    return {
        "answer": "Sorry — I couldn't reach the race data just now. Please try again.",
        "race_time_s": int(now.get("race_time_s", 0)),
        "race_wall_time_ns": int(now.get("race_wall_time_ns", 0)),
        "now_source": now.get("now_source", "unavailable"),
        "refused_future": is_future_question(question),
        "mode": "llm-error",
        "error": f"{type(exc).__name__}: {exc}",
    }


@app.post(
    "/ask_race_data",
    response_model=AskResponse,
    response_model_exclude_none=True,  # keep success responses clean (no error:null)
    operation_id="ask_race_data",
)
async def ask_race_data_route(req: AskRequest) -> AskResponse:
    """The single operation CX's OpenAPI tool calls. One race-data question,
    answered bounded to the replay's current moment (time-honest)."""
    if DETERMINISTIC:
        return AskResponse(**deterministic_answer(req.question))
    try:
        return AskResponse(**await _run_llm(req.question))
    except Exception as exc:  # noqa: BLE001 — never return an empty body to CX
        logger.exception("ask_race_data LLM run failed: %s", exc)
        return AskResponse(**_error_answer(req.question, exc))


# ---- Optional A2A showcase door (not the CX wire) ----------------------------
if not DETERMINISTIC and os.environ.get("A2A_ENABLED", "0") == "1":
    try:
        from google.adk.a2a.utils.agent_to_a2a import to_a2a

        from race_data_subagent.agent import root_agent

        app.mount("/a2a", to_a2a(root_agent))
        logger.info("A2A door mounted at /a2a (showcase only; not used by CX)")
    except Exception as e:  # noqa: BLE001
        logger.warning("A2A door not mounted: %s", e)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
