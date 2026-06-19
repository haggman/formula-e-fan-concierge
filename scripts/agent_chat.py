"""Terminal chat harness for the Race Engineer agent — full tool-call visibility
PLUS per-step latency telemetry (Q&A latency investigation, 2026-06).

Runs the agent in a persistent session and prints EVERY tool call with its
exact arguments and a truncated response, inline with the conversation —
now with a timing prefix on every event line:

    [+ 14.2s  llm  9.8s] ▶ TOOL CALL get_energy_curve({...})
     ^since the question  ^gap since the previous event. Before a TOOL CALL
      was asked            this gap IS the LLM round — generation plus any
                           silent retry backoff. Before a RESPONSE it is the
                           tool's own execution time (incl. the fe-toolbox
                           network hop for Toolbox tools).

After every answer, one summary line photographs the question:

    ── turn 3 | 41.7s wall | 4 LLM calls | 3 tool calls | prompt 18204 tok (last call) | 6 retry/throttle log lines | max llm gap 22.4s

Reading it against the hypotheses (PACKAGING.md, latency investigation):
  - prompt tokens CLIMBING turn over turn   -> hypothesis 4 (session growth)
  - big "llm" gaps + retry/throttle lines   -> hypothesis 1 (quota backoff)
  - many tool rounds on fused questions     -> hypothesis 2/3 (chain depth)
  - /new resets the turn counter (and the session) — the instant control.

--debug-llm additionally streams the google_genai + httpx logs with
millisecond timestamps, so each retry attempt is visible as it happens.
httpx logs every HTTP request WITH its status code — a 429 shows itself
even though Cloud Logging never says "429" (gRPC code 8 lesson, chunk 13).

WHICH AGENT: resolved through the AGENT_PACKAGE seam (shared/agent_pkg.py).
activate.sh defaults to starter.race_engineer — the student build. To chat
with the reference instead:
    AGENT_PACKAGE=solution.race_engineer python scripts/agent_chat.py

Fully async with ONE event loop for the whole session — required because
ToolboxToolset's HTTP client binds to the loop it first runs on. (The sync
runner.run() spins a fresh loop per question, which kills the toolset after
the first turn: "Event loop is closed".)

Usage:
    python scripts/agent_chat.py
    python scripts/agent_chat.py --debug-llm                 # stream retry/backoff logs live
    python scripts/agent_chat.py --max-response-chars 2000   # show more of tool responses

Commands inside the chat:
    /quit            exit
    /new             start a fresh session (clears history AND the turn counter)

Requires: source activate.sh (env vars + venv), simulator running for live
questions. Same session persists across questions until /new.
"""
from __future__ import annotations

from shared.script_env import require_venv
require_venv()

import argparse
import asyncio
import json
import logging
import time
import uuid

from google.adk.runners import InMemoryRunner
from google.genai import types

from shared.agent_pkg import AGENT_PACKAGE, agent_module

root_agent = agent_module("agent").root_agent

APP_NAME = "race_engineer_chat"
USER_ID = "dev"


# ============================================================================
# LLM-side log telemetry (investigation item i — "free" telemetry)
# ============================================================================


class LlmLogCounter(logging.Handler):
    """Counts retry/throttle-shaped records from the genai + httpx loggers.

    The genai client logs its retry attempts and httpx logs each request's
    status code — but at DEBUG/INFO, normally invisible. This handler counts
    them per question so the summary line can say "6 retry/throttle log
    lines" even when --debug-llm isn't streaming the firehose.
    """

    KEYWORDS = ("retry", "retrying", "backoff", "429", "resource_exhausted",
                "resource exhausted", "503", "unavailable", "deadline")

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.hits = 0
        self.samples: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
        except Exception:
            return
        low = msg.lower()
        if any(k in low for k in self.KEYWORDS):
            self.hits += 1
            if len(self.samples) < 5:
                self.samples.append(f"{record.name}: {msg[:180]}")

    def take(self) -> tuple[int, list[str]]:
        """Return and reset the per-question tally."""
        hits, samples = self.hits, self.samples
        self.hits, self.samples = 0, []
        return hits, samples


def setup_llm_telemetry(debug: bool) -> LlmLogCounter:
    """Wire the counter (always) and live log streaming (--debug-llm) onto
    the loggers that photograph the retry chain: google_genai (the SDK logs
    its retry attempts) and httpx (logs every request + status code)."""
    counter = LlmLogCounter()
    stream: logging.Handler
    if debug:
        stream = logging.StreamHandler()
        stream.setLevel(logging.DEBUG)
        stream.setFormatter(logging.Formatter(
            "      %(asctime)s.%(msecs)03d %(name)s %(levelname)s: %(message)s",
            "%H:%M:%S"))
    else:
        # Keep real warnings visible even with propagation off.
        stream = logging.StreamHandler()
        stream.setLevel(logging.WARNING)
    for name in ("google_genai", "google.genai", "httpx"):
        lg = logging.getLogger(name)
        lg.setLevel(logging.INFO if name == "httpx" else logging.DEBUG)
        lg.addHandler(counter)
        lg.addHandler(stream)
        lg.propagate = False  # we own these records now; avoid double prints
    return counter


# ============================================================================
# Formatting helpers (unchanged)
# ============================================================================


def fmt_args(args: dict, limit: int = 400) -> str:
    s = json.dumps(args, default=str)
    return s if len(s) <= limit else s[:limit] + f"... (+{len(s)-limit} chars)"


def fmt_response(resp, limit: int) -> str:
    s = json.dumps(resp, default=str) if not isinstance(resp, str) else resp
    return s if len(s) <= limit else s[:limit] + f"... (+{len(s)-limit} chars)"


async def make_session(runner: InMemoryRunner) -> str:
    session_id = f"chat-{uuid.uuid4().hex[:8]}"
    await runner.session_service.create_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session_id
    )
    return session_id


# ============================================================================
# One question, fully instrumented
# ============================================================================


async def ask(
    runner: InMemoryRunner,
    session_id: str,
    question: str,
    resp_limit: int,
    turn: int,
    counter: LlmLogCounter,
) -> None:
    msg = types.Content(role="user", parts=[types.Part(text=question)])
    t0 = time.monotonic()
    last_event = t0
    llm_calls = 0          # events carrying usage_metadata = one LLM response each
    tool_calls = 0
    prompt_tokens: int | None = None   # last LLM call's input size — the
                                       # session-growth (hypothesis 4) signal
    max_llm_gap = 0.0
    final_text: list[str] = []

    async for event in runner.run_async(
        user_id=USER_ID, session_id=session_id, new_message=msg
    ):
        now = time.monotonic()
        gap = now - last_event
        last_event = now

        calls = event.get_function_calls()
        responses = event.get_function_responses()

        # Gap attribution: an event that CARRIES tool calls (or final text)
        # was produced by the model — its gap is the LLM round, retries and
        # all. An event carrying tool RESPONSES took that long to execute.
        if calls:
            max_llm_gap = max(max_llm_gap, gap)
            for call in calls:
                tool_calls += 1
                print(f"  [+{now-t0:5.1f}s  llm {gap:5.1f}s] "
                      f"▶ TOOL CALL  {call.name}({fmt_args(dict(call.args or {}))})")
        for fr in responses:
            print(f"  [+{now-t0:5.1f}s tool {gap:5.1f}s] "
                  f"◀ RESPONSE   {fr.name}: {fmt_response(fr.response, resp_limit)}")

        usage = getattr(event, "usage_metadata", None)
        if usage is not None:
            llm_calls += 1
            pt = getattr(usage, "prompt_token_count", None)
            if pt:
                prompt_tokens = pt

        if event.is_final_response() and event.content and event.content.parts:
            if not calls and not responses:
                max_llm_gap = max(max_llm_gap, gap)
            for part in event.content.parts:
                if getattr(part, "text", None):
                    final_text.append(part.text)

    wall = time.monotonic() - t0
    print()
    print("ENGINEER:", "".join(final_text).strip() or "(no text response)")

    hits, samples = counter.take()
    tok = f"{prompt_tokens}" if prompt_tokens else "?"
    print(f"\n  ── turn {turn} | {wall:.1f}s wall | {llm_calls} LLM calls | "
          f"{tool_calls} tool calls | prompt {tok} tok (last call) | "
          f"{hits} retry/throttle log lines | max llm gap {max_llm_gap:.1f}s")
    if hits and samples:
        for line in samples[:3]:
            print(f"       · {line}")
        if hits > 3:
            print(f"       · ... (+{hits - 3} more — rerun with --debug-llm to stream them live)")


# ============================================================================
# REPL
# ============================================================================


async def amain(resp_limit: int, debug_llm: bool) -> None:
    counter = setup_llm_telemetry(debug_llm)
    runner = InMemoryRunner(agent=root_agent, app_name=APP_NAME)
    session_id = await make_session(runner)
    turn = 0
    print(f"Race Engineer chat — package {AGENT_PACKAGE}, session {session_id}")
    print("Tool calls print inline with timing. /new = fresh session "
          "(resets the turn counter), /quit = exit.")
    print("Telemetry: per-turn summary always on"
          + ("; --debug-llm streaming google_genai+httpx logs.\n" if debug_llm
             else "; add --debug-llm to stream the retry log live.\n"))

    while True:
        try:
            # input() blocks, but this is a single-user dev REPL — nothing
            # else needs the loop while we wait for the human.
            q = await asyncio.to_thread(input, "YOU: ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        q = q.strip()
        if not q:
            continue
        if q == "/quit":
            break
        if q == "/new":
            session_id = await make_session(runner)
            turn = 0
            print(f"(fresh session {session_id} — turn counter reset)\n")
            continue
        print()
        turn += 1
        try:
            await ask(runner, session_id, q, resp_limit, turn, counter)
        except Exception as e:
            counter.take()  # don't let this turn's hits bleed into the next
            print(f"  ✗ run failed: {type(e).__name__}: {e}")
        print()

    await runner.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-response-chars", type=int, default=600,
                        help="truncate printed tool responses to this length")
    parser.add_argument("--debug-llm", action="store_true",
                        help="stream google_genai + httpx logs with ms "
                             "timestamps — photographs retry backoff live")
    args = parser.parse_args()
    asyncio.run(amain(args.max_response_chars, args.debug_llm))


if __name__ == "__main__":
    main()
