"""The engineer's trigger loop as a service component (chunk 9, Pass 2;
chunk 13 rewires invocation through frontend/agent_client.py; packaging P1.2
resolves the agent package through the AGENT_PACKAGE seam).

This is scripts/local_test.py's loop, re-homed: poll Firestore → score with
shared.scorer → fire the agent on triggers — except deliveries are broadcast
over the websocket as {type: "radio"} messages instead of printed. All the
chunk 8 policy survives intact: per-type debounce, the pending must-say hold
(fresh snapshot at delivery, TTL expiry), the overdue-summary guarantee, the
tool/time budget, and drop-don't-crash on failures.

Chunk 13: the loop no longer owns an ADK runner. It calls
agent_client.fire()/ask() and doesn't know whether the agent runs in-process
(AGENT_MODE=local) or on the deployed Agent Engine (AGENT_MODE=engine). The
budget mechanism differs by mode — RunConfig ceiling locally, wall-clock
timeout remotely — but the loop's drop-on-failure handling covers both.

Packaging P1.2: config/prompts/snapshot/state_client resolve through
agent_module() (the AGENT_PACKAGE seam), so when a student's
starter.race_engineer is active, the triggers carry THEIR prompts and
persona — not the reference's. The trigger POLICY below is infrastructure
and stays given; only what the agent is told comes from the active package.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import Counter
from typing import Awaitable, Callable

from frontend.agent_client import agent_module, make_agent_client
from shared.models import EventType
from shared.scorer import DEFAULT_THRESHOLD, score

# --- resolved through the AGENT_PACKAGE seam (starter vs solution) ---
_config = agent_module("config")
_prompts = agent_module("prompts")
OUR_CAR_NUMBER = _config.OUR_CAR_NUMBER
build_event_reaction_prompt = _prompts.build_event_reaction_prompt
build_lap_summary_prompt = _prompts.build_lap_summary_prompt
snapshot_dict = agent_module("snapshot").snapshot_dict
get_state_client = agent_module("tools.state_client").get_state_client

logger = logging.getLogger("engineer")

AM_LOOKBACK_S = 30
FAIL_COOLDOWN_S = 5
MUST_SAY_TTL_S = 25

Broadcast = Callable[[dict], Awaitable[None]]


class EngineerLoop:
    """Background trigger loop. One instance per process."""

    def __init__(
        self,
        broadcast: Broadcast,
        *,
        threshold: int = DEFAULT_THRESHOLD,
        debounce_s: float = 15.0,
        must_say_gap_s: float = 5.0,
        summary_every: int = 2,
        poll_s: float = 2.0,
    ) -> None:
        self.broadcast = broadcast
        self.threshold = threshold
        self.debounce_s = debounce_s
        self.must_say_gap_s = must_say_gap_s
        self.summary_every = summary_every
        self.poll_s = poll_s
        self.client = get_state_client()
        self.agent = make_agent_client()  # local or engine, per AGENT_MODE
        # Per-race call-type scoreboard: fired:<kind> / dropped:<kind> /
        # suppressed / expired:must_say. Logged every ~120s and dumped +
        # cleared on replay restart, so each race gets its own baseline.
        self.stats: Counter = Counter()
        self._stats_logged_wall = time.monotonic()

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
                # subset of dropped: the fire died THROTTLED after the
                # SDK's retries gave up
                self.stats[f"throttled:{kind}"] += 1
            return False
        logger.info("[t=%s lap %s] %s (%.1fs, %d tools): %s",
                    now_s, lap, kind, secs, tools, text)
        await self.broadcast({
            "type": "radio", "kind": kind,
            "race_time_s": now_s, "lap": lap,
            "reason": reason, "text": text,
            "secs": round(secs, 1), "tools": tools,
        })
        self.stats[f"fired:{kind}"] += 1
        return True

    async def ask(self, question: str) -> str:
        """Pit-wall Q&A. Persistent session (follow-ups keep context); the
        agent fetches whatever it needs — triggers carry snapshots, questions
        don't. Raises on failure; the websocket layer reports it."""
        return await self.agent.ask(question)

    # ------------------------------------------------------------------
    # The loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        last_scored_to: int | None = None
        last_fire_wall: float = -1e9
        prev_position: int | None = None
        last_lap: int | None = None
        last_summary_lap: int | None = None
        due_summary_lap: int | None = None  # sticky: an owed summary survives blocked polls
        pending_must_say = None  # (TriggerCandidate, race_time_s first seen)

        logger.info("engineer loop online — threshold=%s debounce=%ss "
                    "must-say gap=%ss summary every %s laps",
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

            our = state.car_by_number(OUR_CAR_NUMBER)
            now_s = state.race_time_s

            if last_scored_to is not None and now_s < last_scored_to - 5:
                # race time went backwards: replay restarted — flush loop state
                logger.info("replay restart detected (t=%s < %s) — resetting", now_s, last_scored_to)
                if self.stats:
                    logger.info("scoreboard (race just ended): %s",
                                dict(sorted(self.stats.items())))
                    self.stats.clear()
                last_scored_to = None
                prev_position = None
                last_lap = None
                last_summary_lap = None
                due_summary_lap = None
                pending_must_say = None
                self.agent.reset_qa_session()  # Finding #10: a new race
                logger.info("Q&A session rotated for the new race")

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
                our_car=OUR_CAR_NUMBER,
                recent_am_activations=len(am_recent),
                prev_our_position=prev_position,
            )
            last_scored_to = now_s
            prev_position = our.position if our else prev_position

            lap_now = our.current_lap if our else None
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

            if pending_must_say and wall_gap >= self.must_say_gap_s:
                attempted = True
                cand, _ = pending_must_say
                snap = snapshot_dict(state)
                prompt = build_event_reaction_prompt(
                    reason=cand.reason,
                    snapshot_json=json.dumps(snap),
                    events_json=json.dumps(cand.events),
                )
                fired = await self._deliver("must_say", prompt, now_s, lap_now, cand.reason)
                if fired:
                    pending_must_say = None
            elif due_summary_lap is not None and wall_gap >= self.must_say_gap_s:
                attempted = True
                snap = snapshot_dict(state)
                prompt = build_lap_summary_prompt(
                    lap_number=due_summary_lap, snapshot_json=json.dumps(snap),
                )
                fired = await self._deliver("lap_summary", prompt, now_s, lap_now,
                                            f"end of lap {due_summary_lap}")
                if fired:
                    last_summary_lap = due_summary_lap
                    due_summary_lap = None
            elif best and best.score >= self.threshold and wall_gap >= self.debounce_s:
                attempted = True
                snap = snapshot_dict(state)
                prompt = build_event_reaction_prompt(
                    reason=best.reason,
                    snapshot_json=json.dumps(snap),
                    events_json=json.dumps(best.events),
                )
                fired = await self._deliver("event", prompt, now_s, lap_now, best.reason)
            elif lap_changed and wall_gap >= self.debounce_s:
                attempted = True
                snap = snapshot_dict(state)
                prompt = build_lap_summary_prompt(
                    lap_number=completed_lap, snapshot_json=json.dumps(snap),
                )
                fired = await self._deliver("lap_summary", prompt, now_s, lap_now,
                                            f"end of lap {completed_lap}")
                if fired:
                    last_summary_lap = completed_lap
            elif best and best.score >= self.threshold:
                # over threshold but inside the debounce window — counted
                # so Test 1 can see how often the gate earns its keep
                self.stats["suppressed"] += 1

            if fired:
                last_fire_wall = time.monotonic()
            elif attempted:
                # delivery failed — cooldown before any retry, don't hammer
                last_fire_wall = time.monotonic() - self.debounce_s + FAIL_COOLDOWN_S

            if time.monotonic() - self._stats_logged_wall >= 120 and self.stats:
                logger.info("scoreboard: %s", dict(sorted(self.stats.items())))
                self._stats_logged_wall = time.monotonic()

            await asyncio.sleep(self.poll_s)

    async def close(self) -> None:
        await self.agent.close()
