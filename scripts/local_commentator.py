"""Local harness for the COMMENTATOR — watch the continuous play-by-play in your
terminal, no frontend needed.

Mirrors frontend/commentator_loop.py: each beat reads the live field, asks
shared.scorer to RANK what's happened (front-weighted, selected-car boosted),
hands the model the top action + running order + the last few lines it said, and
prints the next 2-3 sentences. A continuous stream, not sparse bulletins.

WHICH AGENT: resolved through the AGENT_PACKAGE seam (shared/agent_pkg.py) —
activate.sh defaults to starter.commentator. The reference:
    AGENT_PACKAGE=solution.commentator python scripts/local_commentator.py ...

SELECTION: --select <car> makes the commentary narrow onto that car (as the UI's
click does). Omit it for front-of-field play-by-play.

Usage (simulator playing; 2x is fine):
    python scripts/local_commentator.py --duration 180
    python scripts/local_commentator.py --select 13 --duration 180
"""
from __future__ import annotations

from shared.script_env import require_venv
require_venv()

import argparse
import asyncio
import json
import time
import uuid
from collections import Counter, deque

from google.adk.agents.run_config import RunConfig
from google.adk.runners import InMemoryRunner
from google.genai import types

from shared.agent_pkg import AGENT_PACKAGE, agent_module
from shared.models import EventType
from shared.scorer import score
from shared.state_client import get_state_client

# --- resolved through the AGENT_PACKAGE seam (starter vs solution commentator) ---
root_agent = agent_module("agent").root_agent
build_commentary_prompt = agent_module("prompts").build_commentary_prompt
snapshot_dict = agent_module("snapshot").snapshot_dict

APP_NAME = "commentator_local_test"
USER_ID = "harness"
AM_LOOKBACK_S = 30
MAX_LLM_CALLS_PER_LINE = 3   # the commentator narrates from the prompt; ~no tools


def watching_line(state, selected_car):
    if selected_car is None:
        return ""
    car = state.car_by_number(selected_car)
    drv = f" ({car.driver_short_name})" if car else ""
    return (f"THE FAN IS WATCHING car {selected_car}{drv} — make that car your main "
            "story this turn: lead with it and its battle, then glance at the front.")


async def fire(runner: InMemoryRunner, prompt: str) -> tuple[str, float]:
    session_id = f"line-{uuid.uuid4().hex[:8]}"
    await runner.session_service.create_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session_id
    )
    msg = types.Content(role="user", parts=[types.Part(text=prompt)])
    t0 = time.monotonic()
    final: list[str] = []
    async for event in runner.run_async(
        user_id=USER_ID, session_id=session_id, new_message=msg,
        run_config=RunConfig(max_llm_calls=MAX_LLM_CALLS_PER_LINE),
    ):
        if event.is_final_response() and event.content and event.content.parts:
            for part in event.content.parts:
                if getattr(part, "text", None):
                    final.append(part.text)
    return "".join(final).strip(), time.monotonic() - t0


async def amain(args: argparse.Namespace) -> None:
    runner = InMemoryRunner(agent=root_agent, app_name=APP_NAME)
    client = get_state_client()
    selected_car = args.select

    recent: deque[str] = deque(maxlen=args.recent_window)
    prev_positions: dict[int, int] = {}
    last_scored_to: int | None = None
    stats = Counter()

    print(f"Commentator harness — package={AGENT_PACKAGE}, "
          f"watching={'field-wide' if selected_car is None else f'car {selected_car}'}, "
          f"reading gap={args.reading_gap}s, duration={args.duration}s\n")

    t_start = time.monotonic()
    while time.monotonic() - t_start < args.duration:
        state = client.get_race_state(fresh=True)
        if state is None:
            print("  (no RaceState yet — is the simulator running?)")
            await asyncio.sleep(args.poll)
            continue

        now_s = state.race_time_s
        from_s = (last_scored_to + 1) if last_scored_to is not None else max(0, now_s - 20)
        new_events = client.query_events(
            from_race_time_s=from_s, to_race_time_s=now_s, limit=100,
        ) if now_s >= from_s else []
        am_recent = client.query_events(
            from_race_time_s=max(0, now_s - AM_LOOKBACK_S), to_race_time_s=now_s,
            event_types=[EventType.ATTACK_MODE_ACTIVATED], limit=50,
        )

        candidates = score(
            state, new_events,
            selected_car=selected_car,
            recent_am_activations=len(am_recent),
            prev_positions=prev_positions or None,
        )
        last_scored_to = now_s
        prev_positions = {c.car_number: c.position for c in state.cars if not c.is_retired}

        action = [c.reason for c in candidates[:args.lead_events]]
        lap_now = state.current_leader_lap
        prompt = build_commentary_prompt(
            recent_lines="\n".join(recent),
            action_json=json.dumps(action),
            snapshot_json=json.dumps(snapshot_dict(state, selected_car)),
            watching=watching_line(state, selected_car),
        )

        try:
            text, secs = await fire(runner, prompt)
        except Exception as e:
            print(f"  ✗ line dropped: {type(e).__name__}: {str(e).splitlines()[0][:140]}")
            stats["dropped"] += 1
            await asyncio.sleep(args.reading_gap)
            continue

        if not text:
            stats["empty"] += 1
            await asyncio.sleep(args.reading_gap)
            continue

        lead = action[0] if action else "(quiet — running order)"
        print(f"[t={now_s} lap {lap_now}] ({secs:.1f}s) ← {lead}")
        print(f"  {text}\n")
        stats["fired"] += 1
        recent.append(text)
        await asyncio.sleep(args.reading_gap)

    print(f"Done. {dict(stats)}")
    await runner.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=int, default=180,
                        help="run for this many wall seconds")
    parser.add_argument("--select", type=int, default=None,
                        help="narrow commentary onto this car (field-wide if omitted)")
    parser.add_argument("--reading-gap", type=float, default=4.0,
                        help="pause after each line (≈ time to read it) before the next")
    parser.add_argument("--lead-events", type=int, default=4,
                        help="how many ranked items to hand the model per line")
    parser.add_argument("--recent-window", type=int, default=4,
                        help="how many recent lines to feed back for continuity")
    parser.add_argument("--poll", type=int, default=2)
    args = parser.parse_args()
    try:
        asyncio.run(amain(args))
    except KeyboardInterrupt:
        print("\nStopped (Ctrl-C).")


if __name__ == "__main__":
    main()
