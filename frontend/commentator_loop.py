"""The commentator's loop — a CONTINUOUS play-by-play broadcaster.

RE-AIMED twice from Ch2. Ch2's engineer loop (and our first commentator pass)
used the scorer as a SILENCE GATE: stay quiet unless something clears a
threshold + debounce — the right instinct for a race engineer who must not
distract the driver. A live commentator is the opposite job: keep talking. So
here the scorer is demoted from gate to **director**:

  every beat (paced to reading time) →
    1. read the live field,
    2. ask shared.scorer to RANK what's happened since the last beat
       (front-of-field weighted, selected-car boosted),
    3. hand the model the top action + the running order + the LAST FEW LINES it
       said, and get back 2-3 flowing sentences that continue the call,
    4. broadcast it; in quiet spells it still speaks (running order / storyline).

The result is a near-continuous stream rather than sparse bulletins. There is no
threshold or debounce — the loop always produces the next line; the director just
decides what that line is ABOUT. Selection still narrows the focus (the scorer
boosts the selected car and the prompt leads with it).

Package resolution: prompts/snapshot resolve through the AGENT_PACKAGE seam
(starter vs solution commentator). State comes from the vendored
shared.state_client.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import Counter, deque
from typing import Awaitable, Callable, Optional

from frontend.agent_client import agent_module, make_agent_client
from shared.models import EventType, RaceState
from shared.scorer import score
from shared.state_client import get_state_client

# --- resolved through the AGENT_PACKAGE seam (starter vs solution commentator) ---
_prompts = agent_module("prompts")
build_commentary_prompt = _prompts.build_commentary_prompt
snapshot_dict = agent_module("snapshot").snapshot_dict

logger = logging.getLogger("commentator")

AM_LOOKBACK_S = 30
FAIL_COOLDOWN_S = 4.0

Broadcast = Callable[[dict], Awaitable[None]]


class CommentatorLoop:
    """Continuous play-by-play loop for the live broadcast commentator."""

    def __init__(
        self,
        broadcast: Broadcast,
        *,
        reading_gap_s: float = 4.0,
        max_lead_events: int = 4,
        recent_window: int = 4,
        poll_s: float = 2.0,
        agent_client=None,
        state_client=None,
    ) -> None:
        self.broadcast = broadcast
        # Pause AFTER each line lands, so the next is generated about when a fan
        # finishes reading the last. The real spacing ≈ generation time + this.
        self.reading_gap_s = reading_gap_s
        # How many ranked items the director hands the model per beat.
        self.max_lead_events = max_lead_events
        # How many recent lines to feed back for continuity / no-repeat.
        self.recent_window = recent_window
        self.poll_s = poll_s
        self.client = state_client if state_client is not None else get_state_client()
        self.agent = agent_client if agent_client is not None else make_agent_client()
        self._selected_car: Optional[int] = None
        self.stats: Counter = Counter()

    # ------------------------------------------------------------------
    # Selection — set from the websocket {type:"select"} message
    # ------------------------------------------------------------------

    def set_selection(self, car_number: Optional[int]) -> None:
        """Update the fan's selected car. None clears it (back to field-wide)."""
        if car_number != self._selected_car:
            logger.info("selection -> %s", car_number if car_number is not None else "field-wide")
        self._selected_car = car_number

    def _watching_line(self, state: RaceState) -> str:
        if self._selected_car is None:
            return ""
        car = state.car_by_number(self._selected_car)
        drv = f" ({car.driver_short_name})" if car else ""
        return (f"THE FAN IS WATCHING car {self._selected_car}{drv} — make that car "
                "your main story this turn: lead with it and its battle, then glance "
                "at the front of the race.")

    # ------------------------------------------------------------------
    # One spoken line
    # ------------------------------------------------------------------

    async def _deliver(self, prompt: str, now_s: int, lap, *, kind: str = "") -> Optional[str]:
        """Fire the agent; broadcast the line. Returns the text, or None on failure."""
        try:
            text, tools, secs = await self.agent.fire(prompt)
        except Exception as e:
            msg = str(e)
            logger.warning("line dropped: %s", msg.splitlines()[0][:160] if msg else type(e).__name__)
            self.stats["dropped"] += 1
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                self.stats["throttled"] += 1
            return None
        if not text:
            self.stats["empty"] += 1
            return None
        logger.info("[t=%s lap %s] (%.1fs, %d tools) sel=%s: %s",
                    now_s, lap, secs, tools, self._selected_car, text)
        await self.broadcast({
            "type": "radio", "kind": kind,
            "race_time_s": now_s, "lap": lap,
            "selected_car": self._selected_car,
            "text": text, "secs": round(secs, 1), "tools": tools,
        })
        self.stats["fired"] += 1
        return text

    async def ask(self, question: str) -> str:
        """Optional fan-initiated question to the commentator (persistent session)."""
        return await self.agent.ask(question)

    # ------------------------------------------------------------------
    # The continuous loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        recent: deque[str] = deque(maxlen=self.recent_window)
        prev_positions: dict[int, int] = {}
        last_scored_to: Optional[int] = None

        logger.info("commentator loop online — continuous play-by-play "
                    "(reading gap %.1fs, lead events %d)",
                    self.reading_gap_s, self.max_lead_events)

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
                # replay restarted — flush continuity so the new race starts clean
                logger.info("replay restart detected (t=%s < %s) — resetting", now_s, last_scored_to)
                if self.stats:
                    logger.info("scoreboard (race ended): %s", dict(sorted(self.stats.items())))
                    self.stats.clear()
                recent.clear()
                prev_positions = {}
                last_scored_to = None
                self.agent.reset_qa_session()

            from_s = (last_scored_to + 1) if last_scored_to is not None else max(0, now_s - 20)
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

            # The DIRECTOR: rank what's happened (front-weighted, selection-boosted).
            candidates = score(
                state, new_events,
                selected_car=self._selected_car,
                recent_am_activations=len(am_recent),
                prev_positions=prev_positions or None,
            )
            last_scored_to = now_s
            prev_positions = {c.car_number: c.position for c in state.cars if not c.is_retired}

            action = [c.reason for c in candidates[:self.max_lead_events]]
            lap_now = state.current_leader_lap
            watching = self._watching_line(state)
            prompt = build_commentary_prompt(
                recent_lines="\n".join(recent),
                action_json=json.dumps(action),
                snapshot_json=json.dumps(snapshot_dict(state, self._selected_car)),
                watching=watching,
            )

            text = await self._deliver(prompt, now_s, lap_now)
            if text:
                recent.append(text)
                await asyncio.sleep(self.reading_gap_s)
            else:
                # generation failed — brief cooldown, then carry on
                await asyncio.sleep(FAIL_COOLDOWN_S)

    async def close(self) -> None:
        await self.agent.close()
