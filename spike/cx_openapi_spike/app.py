"""FastAPI service that serves the spike agent as a clean OpenAPI operation.

Architecture (decided in the CX integration spike): the ADK agent runs on
Cloud Run and IS the service — no separate wrapper. CX's OpenAPI tool calls
POST /ask_race_data directly. (Agent Engine cannot expose a custom OpenAPI
path; see spec/cx_integration_spike.md.)

Two modes, chosen by the DETERMINISTIC env var:
  DETERMINISTIC=1 (default) — POST /ask_race_data calls the ask_race_data tool
      directly. No LLM, no Vertex creds. Reliable first-light wire test and the
      deterministic basis for the live-moment + future-refusal checks.
  DETERMINISTIC=0 — runs the real ADK LlmAgent via a Runner (the lab's actual
      pattern), validating ADK-on-Cloud-Run + Vertex auth too.

Optional A2A door (A2A_ENABLED=1): mounts the agent's A2A app at /a2a for the
Agent Registry / agent-to-agent showcase. A2A is JSON-RPC + agent-card, NOT
OpenAPI — it does not serve CX; it's the "look, it auto-registers" beat.
"""
from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from pydantic import BaseModel, Field

from agent import ask_race_data

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cx_openapi_spike")

DETERMINISTIC = os.environ.get("DETERMINISTIC", "1") == "1"
APP_NAME = "race_data_stub"

app = FastAPI(
    title="Race-Data Subagent (CX integration spike)",
    version="0.1.0",
    description="Stub agent proving the CX -> OpenAPI -> agent wire, time-honest.",
)


class AskRequest(BaseModel):
    question: str = Field(..., description="The fan's race-data question.")


class AskResponse(BaseModel):
    answer: str = Field(..., description="The agent's answer, bounded to the current moment.")
    race_time_s: float = Field(..., description="Replay seconds since green flag.")
    race_wall_time_ns: int = Field(..., description="Computed 2024 wall-clock ns of 'now'.")
    now_source: str = Field(..., description="'firestore' (live) or 'canned' (fallback).")
    refused_future: bool = Field(..., description="True if a future/spoiler question was refused.")
    mode: str = Field(..., description="'deterministic' or 'llm'.")


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "deterministic": DETERMINISTIC}


# Lazy singletons for LLM mode.
_runner = None
_session_service = None


async def _run_llm(question: str) -> dict:
    """Run the real ADK agent once and return ask_race_data's structured result
    plus the model's final text as `answer`."""
    global _runner, _session_service
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    if _runner is None:
        from agent import build_agent

        _session_service = InMemorySessionService()
        _runner = Runner(
            agent=build_agent(), app_name=APP_NAME, session_service=_session_service
        )

    uid, sid = "spike-user", "spike-session"
    await _session_service.create_session(app_name=APP_NAME, user_id=uid, session_id=sid)

    # Capture the tool's structured output for the time-honest fields, while the
    # model produces the natural-language answer.
    tool_result: dict | None = None
    final_text = ""
    msg = types.Content(role="user", parts=[types.Part(text=question)])
    async for event in _runner.run_async(user_id=uid, session_id=sid, new_message=msg):
        for part in (event.content.parts if event.content else []) or []:
            fr = getattr(part, "function_response", None)
            if fr is not None and getattr(fr, "name", "") == "ask_race_data":
                resp = fr.response
                tool_result = resp.get("result", resp) if isinstance(resp, dict) else None
        if event.is_final_response() and event.content and event.content.parts:
            final_text = event.content.parts[0].text or ""

    base = tool_result or ask_race_data(question)  # fall back if we couldn't capture it
    base = dict(base)
    if final_text:
        base["answer"] = final_text
    return base


@app.post("/ask_race_data", response_model=AskResponse, operation_id="ask_race_data")
async def ask_race_data_route(req: AskRequest) -> AskResponse:
    """Answer one race-data question, bounded to the replay's current moment.

    This is the single operation CX's OpenAPI tool calls.
    """
    if DETERMINISTIC:
        result = ask_race_data(req.question)
        result["mode"] = "deterministic"
    else:
        result = await _run_llm(req.question)
        result["mode"] = "llm"
    return AskResponse(**result)


# ---- Optional A2A showcase door ------------------------------------------
if os.environ.get("A2A_ENABLED", "0") == "1":
    try:
        from agent import build_agent
        from google.adk.a2a.utils.agent_to_a2a import to_a2a

        a2a_app = to_a2a(build_agent())
        app.mount("/a2a", a2a_app)
        logger.info("A2A door mounted at /a2a (showcase only; not used by CX)")
    except Exception as e:  # noqa: BLE001
        logger.warning("A2A door not mounted: %s", e)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
