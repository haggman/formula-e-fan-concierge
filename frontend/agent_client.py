"""Agent invocation seam (chunk 13; AGENT_PACKAGE added in packaging P1.2)
— one interface, two runtimes, and now two PACKAGES.

    AGENT_MODE=local   InMemoryRunner in-process. The permanent dev path:
                       edit prompts.py, restart uvicorn, seconds. Chunk 9-11
                       behavior preserved verbatim (RunConfig tool ceilings,
                       fresh session per trigger, persistent Q&A session).

    AGENT_MODE=engine  The deployed Vertex AI Agent Engine, via
                       vertexai.agent_engines. Requires AGENT_ENGINE_RESOURCE
                       (activate.sh exports it from deploy/.engine_resource
                       when present).

    AGENT_PACKAGE      WHICH agent package the frontend loads — the
                       starter/solution seam (packaging P1.2):
                         solution.race_engineer  the complete reference
                         starter.race_engineer   the student build
                       Both packages share the same internal shape (agent,
                       prompts, config, snapshot, tools.state_client), so the
                       frontend resolves all of them through agent_module()
                       below and a student's persona drives the trigger loop
                       exactly as the reference does. Default lives here so
                       the engine-mode container (which never sources
                       activate.sh) gets the reference; activate.sh exports
                       the per-session choice for local work.

The engineer loop and Q&A handler call fire()/ask() and never know which
runtime answered. Same agent shape, two runtimes, two packages, one interface.

Engine-mode design notes:
  - RunConfig(max_llm_calls) does NOT plumb through the engine's query
    interface, so the hard per-call tool ceiling is local-only. Engine mode
    substitutes WALL-CLOCK timeouts (FIRE_TIMEOUT_S / ASK_TIMEOUT_S): per
    chunk 8 policy a stale radio call is worse than a missed one, and the
    caller's drop-with-cooldown handling already owns the failure path.
  - The agent_engines SDK BLOCKS the event loop (even its async_* variants,
    observed live: jerky UI, stalled /api/stt). Engine calls therefore run
    as the sync SDK methods inside asyncio.to_thread — see
    EngineAgentClient's class docstring.
  - The agent module itself is imported ONLY in local mode. Importing it
    constructs the ToolboxToolset and requires TOOLBOX_URL — which the
    engine-mode frontend deliberately does not need (the engine carries its
    own baked .env). The other seam modules (config/prompts/snapshot/
    state_client) import cleanly without ADK in both modes.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
import uuid

logger = logging.getLogger("agent_client")

APP_NAME = "race_engineer_frontend"
USER_ID = "pit_wall"

# Local mode — hard LLM-call ceilings (chunk 8 policy, unchanged)
MAX_LLM_CALLS_PER_TRIGGER = 4
MAX_LLM_CALLS_PER_QA = int(os.environ.get("QA_MAX_LLM_CALLS", "30"))
# Q&A ceiling raised 12 -> 30 + env knob (latency audit, 2026-06-05): a
# legitimate fused chain measured 8 LLM calls, and for HUMAN-initiated Q&A
# a slow-correct answer beats "Radio failure" mid-research. 30 is a circuit
# breaker (~90s worst case at ~3s/call), not policy — only true runaways
# reach it, and a stuck ask must not burn the shared quota pool forever
# (the trigger loop shares the process; the pit wall has no cancel button).
# Effectively unbounded: export QA_MAX_LLM_CALLS=500 (ADK's own default).
# Triggers keep their hard 4 — late-beats-dead is a Q&A-only asymmetry.
QA_SESSION_ID = "pit-wall-qa"  # persistent — Q&A keeps conversational context

# Engine mode — wall-clock ceilings standing in for the RunConfig one
FIRE_TIMEOUT_S = float(os.environ.get("FIRE_TIMEOUT_S", "30"))
ASK_TIMEOUT_S = float(os.environ.get("ASK_TIMEOUT_S", "75"))


# ============================================================================
# The package seam (P1.2; relocated to shared/agent_pkg.py in P1.4 so the dev
# scripts resolve the same package). Re-exported here because engineer_loop
# and main import it from this module.
# ============================================================================

from shared.agent_pkg import AGENT_PACKAGE, agent_module  # noqa: F401  (re-export)


# ============================================================================
# Local: InMemoryRunner in-process (the chunk 9-11 code, re-homed verbatim)
# ============================================================================


class LocalAgentClient:
    """Runs the ADK agent inside the frontend process."""

    def __init__(self) -> None:
        # Deferred imports: only local mode pays the ADK/Toolbox import cost
        # (and the TOOLBOX_URL requirement that comes with the agent module).
        from google.adk.runners import InMemoryRunner

        root_agent = agent_module("agent").root_agent

        self.runner = InMemoryRunner(agent=root_agent, app_name=APP_NAME)
        self._qa_session_id: str | None = None

    async def _run(self, session_id: str, message: str, max_llm_calls: int
                   ) -> tuple[str, int]:
        from google.adk.agents.run_config import RunConfig
        from google.genai import types

        msg = types.Content(role="user", parts=[types.Part(text=message)])
        tool_calls = 0
        final: list[str] = []
        async for event in self.runner.run_async(
            user_id=USER_ID, session_id=session_id, new_message=msg,
            run_config=RunConfig(max_llm_calls=max_llm_calls),
        ):
            tool_calls += len(event.get_function_calls())
            if event.is_final_response() and event.content and event.content.parts:
                for part in event.content.parts:
                    if getattr(part, "text", None):
                        final.append(part.text)
        return "".join(final).strip(), tool_calls

    async def fire(self, prompt: str) -> tuple[str, int, float]:
        """One proactive call in a FRESH session. Returns (text, tools, secs).
        May raise (incl. LlmCallsLimitExceededError) — caller drops the call."""
        session_id = f"trigger-{uuid.uuid4().hex[:8]}"
        await self.runner.session_service.create_session(
            app_name=APP_NAME, user_id=USER_ID, session_id=session_id
        )
        t0 = time.monotonic()
        text, tools = await self._run(session_id, prompt,
                                      MAX_LLM_CALLS_PER_TRIGGER)
        return text, tools, time.monotonic() - t0

    async def ask(self, question: str) -> str:
        """Pit-wall Q&A in a PERSISTENT session — follow-ups keep context.
        The session rotates on replay restart (reset_qa_session), so a new
        race never inherits tool results from the previous one (Finding #10).
        """
        if self._qa_session_id is None:
            self._qa_session_id = f"{QA_SESSION_ID}-{uuid.uuid4().hex[:8]}"
            await self.runner.session_service.create_session(
                app_name=APP_NAME, user_id=USER_ID,
                session_id=self._qa_session_id,
            )
        text, _ = await self._run(self._qa_session_id, question,
                                  MAX_LLM_CALLS_PER_QA)
        return text

    def reset_qa_session(self) -> None:
        """Drop the persistent Q&A session; the next ask starts fresh."""
        self._qa_session_id = None

    async def close(self) -> None:
        await self.runner.close()


# ============================================================================
# Engine: the deployed Agent Engine (sync SDK inside asyncio.to_thread)
# ============================================================================


class EngineAgentClient:
    """Calls the deployed Vertex AI Agent Engine.

    EVENT-LOOP DISCIPLINE: the agent_engines SDK's query path blocks —
    observed live, it stalls the frontend's shared asyncio loop for the
    full duration of each engine call (state broadcasts burst, the lap
    ring sweeps in jerks, /api/stt sits unserved 20-30s). The SDK's
    async_* variants did not save us. So we use the SYNC methods — the
    exact calls scripts/engine_smoke.py validated — and run each whole
    call (create_session + stream_query consumption) in a worker thread
    via asyncio.to_thread. The loop stays free; the UI stays at 1 Hz.

    We never used intermediate streamed events anyway — only the final
    text and the tool-call count — so consuming the stream inside the
    thread loses nothing.
    """

    def __init__(self, resource: str) -> None:
        import vertexai
        from vertexai import agent_engines

        # projects/{project}/locations/{location}/reasoningEngines/{id}
        parts = resource.split("/")
        project, location = parts[1], parts[3]
        vertexai.init(project=project, location=location)
        self.app = agent_engines.get(resource)
        self.resource = resource
        self._qa_session_id: str | None = None
        # One-slot session prefetch for trigger fires: create_session is
        # a control-plane round trip that was sitting INSIDE every fire's
        # latency. Keep one fresh session ready; refill in the background
        # while each query runs. Semantics unchanged — every trigger
        # still gets a session with zero history.
        self._next_session: str | None = None
        self._prefetch_lock = threading.Lock()
        threading.Thread(target=self._prefetch_next, daemon=True).start()

    # ---- sync internals (run inside asyncio.to_thread) ----

    def _new_session_sync(self) -> str:
        session = self.app.create_session(user_id=USER_ID)
        return session["id"] if isinstance(session, dict) else session.id

    def _take_or_create_session(self) -> str:
        """Pop the prefetched session; fall back to a synchronous create
        (prefetch failed, or two fires raced for the slot)."""
        with self._prefetch_lock:
            sid, self._next_session = self._next_session, None
        return sid or self._new_session_sync()

    def _prefetch_next(self) -> None:
        """Refill the slot. Best-effort: on failure the next fire simply
        creates synchronously — never worse than the pre-prefetch path."""
        try:
            sid = self._new_session_sync()
        except Exception:
            return
        with self._prefetch_lock:
            self._next_session = sid

    def _query_sync(self, session_id: str, message: str) -> tuple[str, int]:
        """Consume one query's event stream; return (text, tool_call_count).

        Event shape matches scripts/engine_smoke.py: dicts with
        content.parts[] (function_call / text) and optional error fields.
        """
        tool_calls = 0
        final: list[str] = []
        for event in self.app.stream_query(
            user_id=USER_ID, session_id=session_id, message=message,
        ):
            if not isinstance(event, dict):
                continue
            if event.get("error_message"):
                raise RuntimeError(
                    f"engine error {event.get('error_code')}: "
                    f"{event['error_message'][:200]}"
                )
            for part in (event.get("content") or {}).get("parts", []):
                if part.get("function_call"):
                    tool_calls += 1
                if part.get("text"):
                    final.append(part["text"])
        text = "".join(final).strip()
        if not text:
            # A run that dies mid-flight (quota exhaustion, tool failure) can
            # end its stream with NO error event and NO text. Locally that
            # path raises; remotely it must too, or the loop broadcasts an
            # empty radio box. Raising routes it into drop-with-cooldown.
            raise RuntimeError(
                f"engine returned no text ({tool_calls} tool calls) — "
                "run likely failed server-side; see engine logs"
            )
        return text, tool_calls

    # ---- async surface (what the engineer loop calls) ----

    async def fire(self, prompt: str) -> tuple[str, int, float]:
        """Fresh remote session per trigger; wall-clock timeout in place of
        the local RunConfig ceiling. asyncio.TimeoutError → caller drops.

        Note: on timeout, asyncio abandons the worker thread rather than
        killing it — the engine call runs to completion in the background
        and its result is discarded. Harmless (read-only call, fresh
        session) and exactly the drop-a-stale-call policy we want.
        """
        t0 = time.monotonic()

        def _go() -> tuple[str, int]:
            session_id = self._take_or_create_session()
            # refill the slot WHILE the query runs — creation overlaps
            # model work instead of preceding it
            threading.Thread(target=self._prefetch_next, daemon=True).start()
            return self._query_sync(session_id, prompt)

        text, tools = await asyncio.wait_for(
            asyncio.to_thread(_go), timeout=FIRE_TIMEOUT_S)
        return text, tools, time.monotonic() - t0

    async def ask(self, question: str) -> str:
        """Persistent remote session — and unlike InMemory sessions, this one
        lives on the engine, so it survives a frontend restart."""

        def _go() -> str:
            if self._qa_session_id is None:
                self._qa_session_id = self._new_session_sync()
            text, _ = self._query_sync(self._qa_session_id, question)
            return text

        return await asyncio.wait_for(
            asyncio.to_thread(_go), timeout=ASK_TIMEOUT_S)

    def reset_qa_session(self) -> None:
        """Drop the persistent Q&A session id; the next ask creates a
        fresh session on the engine (the old one is simply abandoned —
        fine in an ephemeral lab project). Finding #10."""
        self._qa_session_id = None

    async def close(self) -> None:
        return None  # nothing to release client-side


# ============================================================================
# Factory — env-selected
# ============================================================================


def make_agent_client():
    """Build the agent client from env: AGENT_MODE = local (default) | engine."""
    mode = os.environ.get("AGENT_MODE", "local").strip().lower()

    if mode == "engine":
        resource = os.environ.get("AGENT_ENGINE_RESOURCE", "").strip()
        if not resource:
            raise RuntimeError(
                "AGENT_MODE=engine requires AGENT_ENGINE_RESOURCE "
                "(the reasoningEngines resource name). source activate.sh "
                "exports it from deploy/.engine_resource after a deploy."
            )
        logger.info("agent client: ENGINE mode — %s "
                    "(fire timeout %.0fs, ask timeout %.0fs)",
                    resource, FIRE_TIMEOUT_S, ASK_TIMEOUT_S)
        return EngineAgentClient(resource)

    if mode != "local":
        raise RuntimeError(f"unknown AGENT_MODE {mode!r} — use 'local' or 'engine'")

    logger.info("agent client: LOCAL mode (InMemoryRunner in-process, "
                "package %s)", AGENT_PACKAGE)
    return LocalAgentClient()
