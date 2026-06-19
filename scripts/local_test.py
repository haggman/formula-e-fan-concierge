"""Local trigger harness — the agent decides when to speak (chunks 7-8).

The loop the frontend's engineer_loop reimplements around a websocket:
  poll Firestore → score with shared.scorer → fire the agent on triggers →
  print radio calls.

WHICH AGENT: resolved through the AGENT_PACKAGE seam (shared/agent_pkg.py)
— with activate.sh defaults this drives YOUR starter agent, which makes it
the fast Tier F surface for trigger tuning: edit shared/scorer.py weights or
your prompts, rerun, read the transcript. To run the reference instead:
    AGENT_PACKAGE=solution.race_engineer python scripts/local_test.py ...

Firing policy (chunk 8, per-type debounce):
  1. MUST-SAY events (our AM transitions, critical/our-car race control)
     pierce the normal debounce — they wait only --must-say-gap (default 5s).
  2. An OVERDUE lap summary (none in the last --summary-every laps) outranks
     normal events and also uses the short gap.
  3. Normal scored events fire above --threshold after --debounce.
  4. On-time lap summaries fill the remaining quiet moments.

Every proactive call runs in a FRESH agent session. The triggering snapshot
(state + events) rides in the prompt, so the agent doesn't re-fetch a world
that has moved on, and proactive calls stay within a small tool budget —
enforced three ways: prompt language (soft), RunConfig(max_llm_calls) per
trigger (hard ceiling), and drop-on-breach via safe_fire (a stale call is
worse than a missed one).

Usage (simulator running; 2x replay recommended for trigger work):
    python scripts/local_test.py --duration 380 --verbose

Notes:
  - Debounce values are WALL-clock seconds; tune per replay speed.
  - Triggers are processed one at a time — an engineer has one mouth.
    Moments we can't get to are dropped, not queued; --verbose shows them.
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
from shared.models import EventType, RaceState
from shared.scorer import DEFAULT_THRESHOLD, TriggerType, score

# --- resolved through the AGENT_PACKAGE seam (starter vs solution) ---
root_agent = agent_module("agent").root_agent
OUR_CAR_NUMBER = agent_module("config").OUR_CAR_NUMBER
_prompts = agent_module("prompts")
build_event_reaction_prompt = _prompts.build_event_reaction_prompt
build_lap_summary_prompt = _prompts.build_lap_summary_prompt
snapshot_dict = agent_module("snapshot").snapshot_dict
get_state_client = agent_module("tools.state_client").get_state_client

APP_NAME = "race_engineer_local_test"
USER_ID = "harness"
AM_LOOKBACK_S = 30            # race-seconds window feeding the cluster rule
FAIL_COOLDOWN_S = 5           # after a failed call, wait this long before retrying
MAX_LLM_CALLS_PER_TRIGGER = 4 # hard ceiling per proactive call (~2 tool rounds + answer)
MUST_SAY_TTL_S = 25           # race-seconds a held must-say stays deliverable


async def fire(runner: InMemoryRunner, prompt: str, verbose: bool) -> tuple[str, int, float]:
    """Run one proactive call in a fresh session. Returns (text, tool_calls, secs).

    May raise — including LlmCallsLimitExceededError when the hard tool-budget
    ceiling trips. Callers use safe_fire, which drops the call and keeps the
    loop alive.
    """
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
    """fire(), but a failure drops the call instead of killing the harness."""
    try:
        return await fire(runner, prompt, verbose)
    except Exception as e:
        msg = str(e).splitlines()[0][:160] if str(e) else type(e).__name__
        print(f"  ✗ call dropped: {type(e).__name__}: {msg}")
        return None


async def amain(args: argparse.Namespace) -> None:
    runner = InMemoryRunner(agent=root_agent, app_name=APP_NAME)
    client = get_state_client()

    last_scored_to: int | None = None
    last_fire_wall: float = -1e9
    prev_position: int | None = None
    last_lap: int | None = None
    last_summary_lap: int | None = None
    pending_must_say = None  # (TriggerCandidate, race_time_s first seen) — held until deliverable
    fired_by = Counter()
    suppressed = failed = 0

    print(f"Local trigger harness — package={AGENT_PACKAGE}, "
          f"threshold={args.threshold}, debounce={args.debounce}s, "
          f"must-say gap={args.must_say_gap}s, "
          f"summary every {args.summary_every} laps, duration={args.duration}s")
    print("Polling for triggers...\n")

    async def deliver(label: str, prompt: str, now_s: int, lap_now, detail: str,
                      snap: dict | None = None) -> bool:
        nonlocal last_fire_wall, failed
        print(f"[t={now_s} lap {lap_now}] TRIGGER {label} — {detail}")
        if args.verbose and snap and snap.get("our"):
            o = snap["our"]
            ahead = snap.get("car_ahead") or {}
            behind = snap.get("car_behind") or {}
            print(f"      snapshot: P{o['position']} lap {o['lap']} "
                  f"e={o['energy_pct_remaining']}% am={'ON' if o['am_active'] else 'off'} "
                  f"ahead={ahead.get('driver','-')} behind={behind.get('driver','-')}")
        result = await safe_fire(runner, prompt, args.verbose)
        if result:
            text, calls, secs = result
            print(f"  ENGINEER: {text}")
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

        our = state.car_by_number(OUR_CAR_NUMBER)
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
            our_car=OUR_CAR_NUMBER,
            recent_am_activations=len(am_recent),
            prev_our_position=prev_position,
        )
        last_scored_to = now_s
        prev_position = our.position if our else prev_position

        lap_now = our.current_lap if our else None
        lap_changed = (
            last_lap is not None and lap_now is not None
            and lap_now > last_lap
            and last_lap >= 1  # lap 0 -> 1 is the green flag, not a completed lap
        )
        completed_lap = last_lap if lap_changed else None
        last_lap = lap_now if lap_now is not None else last_lap
        summary_overdue = lap_changed and (
            last_summary_lap is None
            or (completed_lap - last_summary_lap) >= args.summary_every
        )

        wall_since_fire = time.monotonic() - last_fire_wall
        best = candidates[0] if candidates else None

        # --- must-say hold: per-event rules score NEW events only, so a
        # must-say blocked by the gap would otherwise evaporate by the next
        # poll. Hold the best one until deliverable; expire when stale.
        if best and best.must_say:
            if pending_must_say is None or best.score >= pending_must_say[0].score:
                pending_must_say = (best, now_s)
        if pending_must_say and now_s - pending_must_say[1] > MUST_SAY_TTL_S:
            if args.verbose:
                print(f"[t={now_s}] expired MUST-SAY (held {now_s - pending_must_say[1]}s "
                      f"race time): {pending_must_say[0].reason}")
            pending_must_say = None

        # --- firing policy ---
        if pending_must_say and wall_since_fire >= args.must_say_gap:
            cand, seen_s = pending_must_say
            snap = snapshot_dict(state)  # fresh snapshot; event payload rides along
            prompt = build_event_reaction_prompt(
                reason=cand.reason,
                snapshot_json=json.dumps(snap),
                events_json=json.dumps(cand.events),
            )
            held = now_s - seen_s
            ok = await deliver("event_reaction[MUST-SAY]", prompt, now_s, lap_now,
                               f"score={cand.score} — {cand.reason}"
                               + (f" (held {held}s)" if held else ""))
            if ok:
                pending_must_say = None  # delivered; on failure keep it and retry
        elif summary_overdue and wall_since_fire >= args.must_say_gap:
            snap = snapshot_dict(state)
            prompt = build_lap_summary_prompt(
                lap_number=completed_lap, snapshot_json=json.dumps(snap),
            )
            if await deliver("lap_summary[OVERDUE]", prompt, now_s, lap_now,
                             f"end of lap {completed_lap}", snap=snap):
                last_summary_lap = completed_lap
        elif best and best.score >= args.threshold and wall_since_fire >= args.debounce:
            snap = snapshot_dict(state)
            prompt = build_event_reaction_prompt(
                reason=best.reason,
                snapshot_json=json.dumps(snap),
                events_json=json.dumps(best.events),
            )
            await deliver("event_reaction", prompt, now_s, lap_now,
                          f"score={best.score} — {best.reason}", snap=snap)
        elif lap_changed and wall_since_fire >= args.debounce:
            snap = snapshot_dict(state)
            prompt = build_lap_summary_prompt(
                lap_number=completed_lap, snapshot_json=json.dumps(snap),
            )
            if await deliver("lap_summary", prompt, now_s, lap_now,
                             f"end of lap {completed_lap}", snap=snap):
                last_summary_lap = completed_lap
        else:
            if pending_must_say and args.verbose:
                print(f"[t={now_s}] holding MUST-SAY (gap {wall_since_fire:.0f}s "
                      f"< {args.must_say_gap}s): {pending_must_say[0].reason}")
            if best and best.score >= args.threshold and not best.must_say:
                suppressed += 1
                if args.verbose:
                    print(f"[t={now_s}] suppressed (gap {wall_since_fire:.0f}s): "
                          f"score={best.score} {best.reason}")
            elif args.verbose and best and not best.must_say:
                print(f"[t={now_s}] below threshold: score={best.score} {best.reason}")

        await asyncio.sleep(args.poll)

    print(f"\nDone. Fired: {dict(fired_by)} | suppressed {suppressed} | dropped {failed}")
    await runner.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=int, default=380,
                        help="run for this many wall seconds (380 ≈ laps 1-11 at 2x)")
    parser.add_argument("--poll", type=int, default=2)
    parser.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD)
    parser.add_argument("--debounce", type=int, default=15,
                        help="min wall seconds between normal calls")
    parser.add_argument("--must-say-gap", type=int, default=5,
                        help="min wall seconds before a MUST-SAY or overdue summary")
    parser.add_argument("--summary-every", type=int, default=2,
                        help="guarantee a lap summary at least every N laps")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    asyncio.run(amain(args))


if __name__ == "__main__":
    main()
