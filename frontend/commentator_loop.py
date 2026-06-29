"""The commentator's trigger loop as a service component.

RE-AIM of Ch2's frontend/engineer_loop.py. Same proven shape — poll Firestore
→ score with shared.scorer → fire the agent on triggers → broadcast over the
websocket — and ALL of Ch2's trigger policy survives intact: per-type debounce,
the pending must-say hold (fresh snapshot at delivery, TTL expiry), the
overdue-recap guarantee, the tool/time budget, and drop-don't-crash on failures.

What's NEW for the commentator (the field-wide broadcaster):
  1. SELECTION. The loop holds the fan's currently selected car (set from the
     websocket `{type:"select", car_number}` message via set_selection). It
     threads that into the scorer (selected-car boost) and into the snapshot +
     prompt ("the fan is watching car N"), so commentary follows what the fan
     is watching without going blind to the rest of the field.
  2. FIELD-WIDE POSITION TRACKING. prev_positions is a dict {car: position}
     across polls, not Ch2's single "our position" — swings are detected for
     every car.
  3. LAP BOUNDARIES from the LEADER. Recaps key off current_leader_lap (the
     field's lap), not one car's lap.

Package resolution: config/prompts/snapshot resolve through the AGENT_PACKAGE
seam (shared/agent_pkg.py), so a student's starter.commentator drives the loop
with THEIR persona, exactly as the reference does. The state client is the
vendored shared.state_client (the commentator package has no per-package copy).
The trigger POLICY below is given infrastructure and stays put; only what the
agent is told comes from the active package.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import Counter
from typing import Awaitable, Callable, Optional

from frontend.agent_client import agent_module, make_agent_client
from shared.models import EventType, RaceState
from shared.scorer import DEFAULT_THRESHOLD, score
from shared.state_client import get_state_client

# --- resolved through the AGENT_PACKAGE seam (starter vs solution commentator) ---
_prompts = agent_module("prompts")
build_event_reaction_prompt = _prompts.build_event_reaction_prompt
build_lap_summary_prompt = _prompts.build_lap_summary_prompt
snapshot_dict = agent_module("snapshot").snapshot_dict

logger = logging.getLogger("commentator")

AM_LOOKBACK_S = 30
FAIL_COOLDOWN_S = 5
MUST_SAY_TTL_S = 25

Broadcast = Callable[[dict], Awaitable[None]]


class CommentatorLoop:
    """Background trigger loop for the live broadcast commentator. One per process."""

    def __init__(
        self,
        broadcast: Broadcast,
        *,
        threshold: int = DEFAULT_THRESHOLD,
        debounce_s: float = 15.0,
        must_say_gap_s: float = 5.0,
        summary_every: int = 2,
        poll_s: float = 2.0,
        agent_client=None,
        state_client=None,
    ) -> None:
        self.broadcast = broadcast
        self.threshold = threshold
        self.debounce_s = debounce_s
        self.must_say_gap_s = must_say_gap_s
        self.summary_every = summary_every
        self.poll_s = poll_s
        # Injectable for tests/harnesses; default to the real Firestore reader
        # and the env-selected (local/engine) ADK agent client.
        self.client = state_client if state_client is not None else get_state_client()
        self.agent = agent_client if agent_client is not None else make_agent_client()
        # The car the fan is currently watching (None = pure field-wide).
        # Updated from the websocket {type:"select"} message.
        self._selected_car: Optional[int] = None
        self.stats: Counter = Counter()
        self._stats_logged_wall = time.monotonic()

    # ------------------------------------------------------------------
    # Selection — set from the websocket select message
    # ------------------------------------------------------------------

    def set_selection(self, car_number: Optional[int]) -> None:
        """Update the fan's selected car. None clears it (back to field-wide)."""
        if car_number != self._selected_car:
            logger.info("selection -> %s", car_number if car_number is not None else "field-wide")
        self._selected_car = car_number

    def _watching_line(self, state: RaceState) -> str:
        """The 'fan is watching car N' line injected into the trigger prompt."""
        if self._selected_car is None:
            return ""
        car = state.car_by_number(self._selected_car)
        drv = f" ({car.driver_short_name})" if car else ""
        return (f"THE FAN IS WATCHING car {self._selected_car}{drv} — open the "
                "call on that car and its battle, then widen to the field.")

    # ------------------------------------------------------------------
    # Agent invocation
    # ------------------------------------------------------------------

    async def _deliver(self, kind: str, prompt: str, now_s: int, lap, reason: str) -> bool:
        """Fire the agent; broadcast the call. False (and cooldown) on failure."""
        try:
            text, tools, secs = await self.agent.fire(prompt)
        except Exception as e:
            msg = str(e)
            logger.warning("call dropped (%s): %s", kind,
                           msg.splitlines()[0][:160] if msg else type(e).__name__)
            self.stats[f"dropped:{kind}"] += 1
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                self.stats[f"throttled:{kind}"] += 1
            return False
        logger.info("[t=%s lap %s] %s (%.1fs, %d tools) sel=%s: %s",
                    now_s, lap, kind, secs, tools, self._selected_car, text)
        await self.broadcast({
            "type": "radio", "kind": kind,
            "race_time_s": now_s, "lap": lap,
            "selected_car": self._selected_car,
            "reason": reason, "text": text,
            "secs": round(secs, 1), "tools": tools,
        })
        self.stats[f"fired:{kind}"] += 1
        return True

    async def ask(self, question: str) -> str:
        """Optional fan-initiated question to the commentator. Persistent
        session; raises on failure (the websocket layer reports it)."""
        return await self.agent.ask(question)

    # ------------------------------------------------------------------
    # The loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        last_scored_to: int | None = None
        last_fire_wall: float = -1e9
        prev_positions: dict[int, int] = {}
        last_lap: int | None = None
        last_summary_lap: int | None = None
        due_summary_lap: int | None = None  # sticky: an owed recap survives blocked polls
        pending_must_say = None  # (TriggerCandidate, race_time_s first seen)

        logger.info("commentator loop online — threshold=%s debounce=%ss "
                    "must-say gap=%ss recap every %s laps",
                    self.threshold, self.debounce_s, self.must_say_gap_s,
                    self.summary_every)

        while True:
            try:
                state = self.client.get_race_state(fresh=True)
            except Exception:
                logger.exception("state read failed")
                state = None
            if state is None:
                await asyncio.sleep(self.poll_s)
                continue

            now_s = state.race_time_s

            if last_scored_to is not None and now_s < last_scored_to - 5:
                # race time went backwards: replay restarted — flush loop state
                logger.info("replay restart detected (t=%s < %s) — resetting", now_s, last_scored_to)
                if self.stats:
                    logger.info("scoreboard (race just ended): %s",
                                dict(sorted(self.stats.items())))
                    self.stats.clear()
                last_scored_to = None
                prev_positions = {}
                last_lap = None
                last_summary_lap = None
                due_summary_lap = None
                pending_must_say = None
                self.agent.reset_qa_session()

            from_s = (last_scored_to + 1) if last_scored_to is not None \
                else max(0, now_s - int(self.poll_s) * 10)
            try:
                new_events = self.client.query_events(
                    from_race_time_s=from_s, to_race_time_s=now_s, limit=100,
                ) if now_s >= from_s else []
                am_recent = self.client.query_events(
                    from_race_time_s=max(0, now_s - AM_LOOKBACK_S),
                    to_race_time_s=now_s,
                    event_types=[EventType.ATTACK_MODE_ACTIVATED], limit=50,
                )
            except Exception:
                logger.exception("event read failed")
                await asyncio.sleep(self.poll_s)
                continue

            candidates = score(
                state, new_events,
                selected_car=self._selected_car,
                recent_am_activations=len(am_recent),
                prev_positions=prev_positions or None,
            )
            last_scored_to = now_s
            # Refresh field-wide position map for the NEXT poll's swing detection.
            prev_positions = {
                c.car_number: c.position for c in state.cars if not c.is_retired
            }

            lap_now = state.current_leader_lap
            lap_changed = (
                last_lap is not None and lap_now is not None
                and lap_now > last_lap and last_lap >= 1
            )
            completed_lap = last_lap if lap_changed else None
            last_lap = lap_now if lap_now is not None else last_lap
            if lap_changed and (
                last_summary_lap is None
                or (completed_lap - last_summary_lap) >= self.summary_every
            ):
                due_summary_lap = completed_lap  # newer boundary overwrites older debt

            best = candidates[0] if candidates else None
            if best and best.must_say:
                if pending_must_say is None or best.score >= pending_must_say[0].score:
                    pending_must_say = (best, now_s)
            if pending_must_say and now_s - pending_must_say[1] > MUST_SAY_TTL_S:
                logger.info("expired must-say: %s", pending_must_say[0].reason)
                self.stats["expired:must_say"] += 1
                pending_must_say = None

            wall_gap = time.monotonic() - last_fire_wall
            fired = False
            attempted = False
            watching = self._watching_line(state)

            if pending_must_say and wall_gap >= self.must_say_gap_s:
                attempted = True
                cand, _ = pending_must_say
                prompt = build_event_reaction_prompt(
                    reason=cand.reason,
                    snapshot_json=json.dumps(snapshot_dict(state, self._selected_car)),
                    events_json=json.dumps(cand.events),
                    watching=watching,
                )
                fired = await self._deliver("must_say", prompt, now_s, lap_now, cand.reason)
                if fired:
                    pending_must_say = None
            elif due_summary_lap is not None and wall_gap >= self.must_say_gap_s:
                attempted = True
                prompt = build_lap_summary_prompt(
                    lap_number=due_summary_lap,
                    snapshot_json=json.dumps(snapshot_dict(state, self._selected_car)),
                    watching=watching,
                )
                fired = await self._deliver("recap", prompt, now_s, lap_now,
                                            f"end of lap {due_summary_lap}")
                if fired:
                    last_summary_lap = due_summary_lap
                    due_summary_lap = None
            elif best and best.score >= self.threshold and wall_gap >= self.debounce_s:
                attempted = True
                prompt = build_event_reaction_prompt(
                    reason=best.reason,
                    snapshot_json=json.dumps(snapshot_dict(state, self._selected_car)),
                    events_json=json.dumps(best.events),
                    watching=watching,
                )
                fired = await self._deliver("event", prompt, now_s, lap_now, best.reason)
            elif lap_changed and wall_gap >= self.debounce_s:
                attempted = True
                prompt = build_lap_summary_prompt(
                    lap_number=completed_lap,
                    snapshot_json=json.dumps(snapshot_dict(state, self._selected_car)),
                    watching=watching,
                )
                fired = await self._deliver("recap", prompt, now_s, lap_now,
                                            f"end of lap {completed_lap}")
                if fired:
                    last_summary_lap = completed_lap
            elif best and best.score >= self.threshold:
                self.stats["suppressed"] += 1

            if fired:
                last_fire_wall = time.monotonic()
            elif attempted:
                last_fire_wall = time.monotonic() - self.debounce_s + FAIL_COOLDOWN_S

            if time.monotonic() - self._stats_logged_wall >= 120 and self.stats:
                logger.info("scoreboard: %s", dict(sorted(self.stats.items())))
                self._stats_logged_wall = time.monotonic()

            await asyncio.sleep(self.poll_s)

    async def close(self) -> None:
        await self.agent.close()
