"""Local trigger harness for the COMMENTATOR — the broadcaster decides when to
speak, you watch it call the race in your terminal.

The loop frontend/commentator_loop.py reimplements around a websocket:
  poll Firestore "now" → score field-wide with shared.scorer → fire the agent on
  triggers → print the commentary call.

WHICH AGENT: resolved through the AGENT_PACKAGE seam (shared/agent_pkg.py) —
activate.sh defaults to starter.commentator (your build). To run the reference:
    AGENT_PACKAGE=solution.commentator python scripts/local_commentator.py ...

SELECTION (the distinctive beat): pass --select <car> to simulate the fan
clicking a car in the UI. The scorer then boosts events near that car and the
prompt tells the commentator to open on it. Omit --select for pure field-wide.

Firing policy (unchanged from Ch2): must-say events pierce the debounce; an
overdue field recap outranks normal events; normal scored events fire above
--threshold after --debounce; on-time recaps fill the quiet moments. Every call
runs in a FRESH agent session with the triggering snapshot in the prompt.

Usage (simulator running; 2x replay recommended):
    python scripts/local_commentator.py --duration 380 --verbose
    python scripts/local_commentator.py --select 13 --verbose   # follow car 13
"""
from __future__ import annotations

from shared.script_env import require_venv
require_venv()

import argparse
import asyncio
import json
import time
import uuid
from collections import Counter

from google.adk.agents.run_config import RunConfig
from google.adk.runners import InMemoryRunner
from google.genai import types

from shared.agent_pkg import AGENT_PACKAGE, agent_module
from shared.models import EventType
from shared.scorer import DEFAULT_THRESHOLD, score
from shared.state_client import get_state_client

# --- resolved through the AGENT_PACKAGE seam (starter vs solution commentator) ---
root_agent = agent_module("agent").root_agent
_prompts = agent_module("prompts")
build_event_reaction_prompt = _prompts.build_event_reaction_prompt
build_lap_summary_prompt = _prompts.build_lap_summary_prompt
snapshot_dict = agent_module("snapshot").snapshot_dict

APP_NAME = "commentator_local_test"
USER_ID = "harness"
AM_LOOKBACK_S = 30
FAIL_COOLDOWN_S = 5
MAX_LLM_CALLS_PER_TRIGGER = 4
MUST_SAY_TTL_S = 25


def watching_line(state, selected_car):
    if selected_car is None:
        return ""
    car = state.car_by_number(selected_car)
    drv = f" ({car.driver_short_name})" if car else ""
    return (f"THE FAN IS WATCHING car {selected_car}{drv} — open the call on that "
            "car and its battle, then widen to the field.")


async def fire(runner: InMemoryRunner, prompt: str, verbose: bool) -> tuple[str, int, float]:
    session_id = f"trigger-{uuid.uuid4().hex[:8]}"
    await runner.session_service.create_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session_id
    )
    msg = types.Content(role="user", parts=[types.Part(text=prompt)])
    t0 = time.monotonic()
    tool_calls = 0
    final: list[str] = []
    async for event in runner.run_async(
        user_id=USER_ID, session_id=session_id, new_message=msg,
        run_config=RunConfig(max_llm_calls=MAX_LLM_CALLS_PER_TRIGGER),
    ):
        calls = event.get_function_calls()
        tool_calls += len(calls)
        if verbose:
            for c in calls:
                print(f"      ▶ {c.name}({json.dumps(dict(c.args or {}), default=str)[:160]})")
        if event.is_final_response() and event.content and event.content.parts:
            for part in event.content.parts:
                if getattr(part, "text", None):
                    final.append(part.text)
    return "".join(final).strip(), tool_calls, time.monotonic() - t0


async def safe_fire(runner, prompt, verbose) -> tuple[str, int, float] | None:
    try:
        return await fire(runner, prompt, verbose)
    except Exception as e:
        msg = str(e).splitlines()[0][:160] if str(e) else type(e).__name__
        print(f"  ✗ call dropped: {type(e).__name__}: {msg}")
        return None


async def amain(args: argparse.Namespace) -> None:
    runner = InMemoryRunner(agent=root_agent, app_name=APP_NAME)
    client = get_state_client()
    selected_car = args.select

    last_scored_to: int | None = None
    last_fire_wall: float = -1e9
    prev_positions: dict[int, int] = {}
    last_lap: int | None = None
    last_summary_lap: int | None = None
    pending_must_say = None
    fired_by = Counter()
    suppressed = failed = 0

    print(f"Commentator harness — package={AGENT_PACKAGE}, "
          f"watching={'field-wide' if selected_car is None else f'car {selected_car}'}, "
          f"threshold={args.threshold}, debounce={args.debounce}s, "
          f"must-say gap={args.must_say_gap}s, recap every {args.summary_every} laps, "
          f"duration={args.duration}s")
    print("Polling for triggers...\n")

    async def deliver(label: str, prompt: str, now_s: int, lap_now, detail: str) -> bool:
        nonlocal last_fire_wall, failed
        print(f"[t={now_s} lap {lap_now}] TRIGGER {label} — {detail}")
        result = await safe_fire(runner, prompt, args.verbose)
        if result:
            text, calls, secs = result
            print(f"  COMMENTATOR: {text}")
            print(f"  ({secs:.1f}s, {calls} tool calls)\n")
            last_fire_wall = time.monotonic()
            fired_by[label] += 1
            return True
        failed += 1
        last_fire_wall = time.monotonic() - args.debounce + FAIL_COOLDOWN_S
        return False

    t_start = time.monotonic()
    while time.monotonic() - t_start < args.duration:
        state = client.get_race_state(fresh=True)
        if state is None:
            print("  (no RaceState yet — is the simulator running?)")
            await asyncio.sleep(args.poll)
            continue

        now_s = state.race_time_s
        from_s = (last_scored_to + 1) if last_scored_to is not None else max(0, now_s - args.poll * 10)
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

        lap_now = state.current_leader_lap
        lap_changed = (
            last_lap is not None and lap_now is not None
            and lap_now > last_lap and last_lap >= 1
        )
        completed_lap = last_lap if lap_changed else None
        last_lap = lap_now if lap_now is not None else last_lap
        summary_overdue = lap_changed and (
            last_summary_lap is None
            or (completed_lap - last_summary_lap) >= args.summary_every
        )

        wall_since_fire = time.monotonic() - last_fire_wall
        best = candidates[0] if candidates else None
        watching = watching_line(state, selected_car)

        if best and best.must_say:
            if pending_must_say is None or best.score >= pending_must_say[0].score:
                pending_must_say = (best, now_s)
        if pending_must_say and now_s - pending_must_say[1] > MUST_SAY_TTL_S:
            pending_must_say = None

        if pending_must_say and wall_since_fire >= args.must_say_gap:
            cand, _ = pending_must_say
            prompt = build_event_reaction_prompt(
                reason=cand.reason,
                snapshot_json=json.dumps(snapshot_dict(state, selected_car)),
                events_json=json.dumps(cand.events), watching=watching,
            )
            if await deliver("event[MUST-SAY]", prompt, now_s, lap_now,
                             f"score={cand.score} — {cand.reason}"):
                pending_must_say = None
        elif summary_overdue and wall_since_fire >= args.must_say_gap:
            prompt = build_lap_summary_prompt(
                lap_number=completed_lap,
                snapshot_json=json.dumps(snapshot_dict(state, selected_car)),
                watching=watching,
            )
            if await deliver("recap[OVERDUE]", prompt, now_s, lap_now,
                             f"end of lap {completed_lap}"):
                last_summary_lap = completed_lap
        elif best and best.score >= args.threshold and wall_since_fire >= args.debounce:
            prompt = build_event_reaction_prompt(
                reason=best.reason,
                snapshot_json=json.dumps(snapshot_dict(state, selected_car)),
                events_json=json.dumps(best.events), watching=watching,
            )
            await deliver("event", prompt, now_s, lap_now,
                          f"score={best.score} — {best.reason}")
        elif lap_changed and wall_since_fire >= args.debounce:
            prompt = build_lap_summary_prompt(
                lap_number=completed_lap,
                snapshot_json=json.dumps(snapshot_dict(state, selected_car)),
                watching=watching,
            )
            if await deliver("recap", prompt, now_s, lap_now,
                             f"end of lap {completed_lap}"):
                last_summary_lap = completed_lap
        elif args.idle_filler and wall_since_fire >= args.idle_filler:
            # quiet stretch — keep a continuous, radio-like flow
            prompt = build_lap_summary_prompt(
                lap_number=lap_now or 0,
                snapshot_json=json.dumps(snapshot_dict(state, selected_car)),
                watching=watching,
            )
            await deliver("update", prompt, now_s, lap_now, "field update")
        elif best and best.score >= args.threshold and not best.must_say:
            suppressed += 1
            if args.verbose:
                print(f"[t={now_s}] suppressed (gap {wall_since_fire:.0f}s): "
                      f"score={best.score} {best.reason}")

        await asyncio.sleep(args.poll)

    print(f"\nDone. Fired: {dict(fired_by)} | suppressed {suppressed} | dropped {failed}")
    await runner.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=int, default=380,
                        help="run for this many wall seconds (380 ≈ laps 1-11 at 2x)")
    parser.add_argument("--select", type=int, default=None,
                        help="simulate the fan watching this car number (field-wide if omitted)")
    parser.add_argument("--poll", type=int, default=2)
    parser.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD)
    parser.add_argument("--debounce", type=int, default=8,
                        help="min wall seconds between normal calls")
    parser.add_argument("--must-say-gap", type=int, default=5,
                        help="min wall seconds before a must-say or overdue recap")
    parser.add_argument("--summary-every", type=int, default=1,
                        help="guarantee a field recap at least every N laps")
    parser.add_argument("--idle-filler", type=int, default=12,
                        help="if nothing fired in this many wall seconds, drop in a "
                             "field update for continuous flow (0 disables)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(amain(args))
    except KeyboardInterrupt:
        print("\nStopped (Ctrl-C).")


if __name__ == "__main__":
    main()
