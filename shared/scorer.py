"""Significance scorer — decides when the race engineer should speak.

PURE AND DETERMINISTIC: no I/O, no clocks, no randomness. Same inputs →
same output, always. The caller (scripts/local_test.py now, the frontend
service in chunk 9) owns polling, debounce, and lap-change scheduling.

Three trigger types in the system:
  - EVENT_REACTION: produced HERE when something significant happens
  - LAP_SUMMARY:    scheduled by the CALLER on lap change (not scored)
  - QA:             user-initiated, never scored

Scoring model: each rule emits a TriggerCandidate with a score 0-100 and a
human-readable reason. The caller fires the top candidate if it clears the
threshold and the debounce window. All weights are tunable constants below —
chunk 8 iterates on these against laps 1-10.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from shared.models import Event, EventType, RaceState

# ============================================================================
# Tunable weights (chunk 8 dials)
# ============================================================================

DEFAULT_THRESHOLD = 60          # candidates below this never fire

SCORE_WE_GOT_PASSED = 90        # being overtaken is the most urgent news
SCORE_WE_PASSED = 80
SCORE_OUR_AM_ACTIVATED = 85
SCORE_OUR_AM_DEACTIVATED = 75
SCORE_AM_CLUSTER = 75           # >= AM_CLUSTER_MIN activations in lookback
AM_CLUSTER_MIN = 3
SCORE_RIVAL_AM = 65             # car directly ahead/behind activates
SCORE_POSITION_SWING_BASE = 60  # + 5 per net position beyond the first
POSITION_SWING_MIN = 2          # net positions vs previous check

# Race control severity by category prefix (first match wins)
RC_SEVERITY = [
    ("flag.chequered", 95),
    ("safety_car", 95),
    ("flag.red", 95),
    ("flag.double_yellow", 70),
    ("flag.yellow", 65),
    ("penalty", 60),            # bumped to RC_INVOLVES_US if it names us
    ("incident", 45),           # ditto
    ("flag.green", 55),
    ("pit", 30),
]
RC_INVOLVES_US = 88             # any RC message naming our car


class TriggerType(str, Enum):
    EVENT_REACTION = "event_reaction"
    LAP_SUMMARY = "lap_summary"
    QA = "qa"


class TriggerCandidate(BaseModel):
    """One scored reason to speak. Caller fires the best one above threshold.

    must_say marks moments the engineer cannot stay silent on (our own AM
    transitions, critical race control, RC naming us). The scorer CLASSIFIES;
    the caller decides what must_say buys (a shorter debounce, typically).
    """
    trigger_type: TriggerType
    score: int
    reason: str
    must_say: bool = False
    events: list[dict] = Field(default_factory=list)  # triggering event payloads


# ============================================================================
# Scoring
# ============================================================================


def score(
    state: RaceState,
    new_events: list[Event],
    *,
    our_car: int = 13,
    recent_am_activations: int = 0,
    prev_our_position: Optional[int] = None,
) -> list[TriggerCandidate]:
    """Score the current moment. Returns candidates sorted best-first.

    Args:
      state: current RaceState.
      new_events: events NOT YET SCORED (since the caller's last check).
        Per-event rules fire on these only, so the caller never double-fires.
      our_car: our car number.
      recent_am_activations: count of field AM activations in the caller's
        lookback window (~30 race-seconds) — feeds the cluster rule, which
        needs a wider view than one polling interval.
      prev_our_position: our position at the caller's previous check, for
        the position-swing rule. None on the first check.
    """
    candidates: list[TriggerCandidate] = []
    our_state = state.car_by_number(our_car)

    for e in new_events:
        payload = {
            "event_type": e.event_type.value,
            "race_time_s": e.race_time_s,
            "car_number": e.car_number,
            "data": e.data,
        }

        if e.event_type == EventType.OVERTAKE:
            other = str(e.data.get("participant"))
            gained = e.data.get("position_change", 0) < 0
            if e.car_number == our_car and other == str(our_car):
                # Source-data glitch: one record has subject == other (a car
                # "overtaking itself"). Known artifact — never score it.
                continue
            if e.car_number == our_car:
                candidates.append(TriggerCandidate(
                    trigger_type=TriggerType.EVENT_REACTION,
                    score=SCORE_WE_PASSED if gained else SCORE_WE_GOT_PASSED,
                    reason=(f"we {'passed' if gained else 'were passed by'} "
                            f"car {other}"),
                    events=[payload],
                ))
            elif other == str(our_car):
                they_gained = e.data.get("position_change", 0) < 0
                candidates.append(TriggerCandidate(
                    trigger_type=TriggerType.EVENT_REACTION,
                    score=SCORE_WE_GOT_PASSED if they_gained else SCORE_WE_PASSED,
                    reason=(f"car {e.car_number} "
                            f"{'passed us' if they_gained else 'lost a place to us'}"),
                    events=[payload],
                ))

        elif e.event_type == EventType.ATTACK_MODE_ACTIVATED:
            if e.car_number == our_car:
                candidates.append(TriggerCandidate(
                    trigger_type=TriggerType.EVENT_REACTION,
                    score=SCORE_OUR_AM_ACTIVATED,
                    reason="our attack mode activated",
                    must_say=True,
                    events=[payload],
                ))
            elif _is_neighbor(state, our_state, e.car_number):
                candidates.append(TriggerCandidate(
                    trigger_type=TriggerType.EVENT_REACTION,
                    score=SCORE_RIVAL_AM,
                    reason=f"car {e.car_number} (directly around us) activated attack mode",
                    events=[payload],
                ))

        elif e.event_type == EventType.ATTACK_MODE_DEACTIVATED:
            if e.car_number == our_car:
                candidates.append(TriggerCandidate(
                    trigger_type=TriggerType.EVENT_REACTION,
                    score=SCORE_OUR_AM_DEACTIVATED,
                    reason="our attack mode finished",
                    must_say=True,
                    events=[payload],
                ))

        elif e.event_type == EventType.RACE_CONTROL:
            category = str(e.data.get("category", ""))
            text = str(e.data.get("text", ""))
            sev = next(
                (s for prefix, s in RC_SEVERITY if category.startswith(prefix)),
                0,
            )
            if _rc_names_us(e, our_car):
                sev = max(sev, RC_INVOLVES_US)
            if sev > 0:
                candidates.append(TriggerCandidate(
                    trigger_type=TriggerType.EVENT_REACTION,
                    score=sev,
                    reason=f"race control: {text}",
                    must_say=sev >= 88,  # safety car/red/chequered, or names us
                    events=[payload],
                ))

    # Field-wide AM cluster (needs the caller's lookback count, not new_events)
    if recent_am_activations >= AM_CLUSTER_MIN:
        candidates.append(TriggerCandidate(
            trigger_type=TriggerType.EVENT_REACTION,
            score=SCORE_AM_CLUSTER,
            reason=(f"attack mode cluster: {recent_am_activations} activations "
                    "across the field in the last half minute"),
        ))

    # Net position swing since the caller's last check
    if (
        prev_our_position is not None
        and our_state is not None
        and abs(our_state.position - prev_our_position) >= POSITION_SWING_MIN
    ):
        delta = prev_our_position - our_state.position  # positive = gained
        candidates.append(TriggerCandidate(
            trigger_type=TriggerType.EVENT_REACTION,
            score=SCORE_POSITION_SWING_BASE + 5 * (abs(delta) - 1),
            reason=(f"net position change: "
                    f"{'gained' if delta > 0 else 'lost'} {abs(delta)} places "
                    f"(P{prev_our_position} -> P{our_state.position})"),
        ))

    candidates.sort(key=lambda c: (c.must_say, c.score), reverse=True)
    return candidates


# ============================================================================
# Helpers
# ============================================================================


def _is_neighbor(state: RaceState, our_state, car_number: int) -> bool:
    """True if car_number is directly ahead of or behind us right now."""
    if our_state is None:
        return False
    other = state.car_by_number(car_number)
    if other is None or other.is_retired:
        return False
    return abs(other.position - our_state.position) == 1


def _rc_names_us(e: Event, our_car: int) -> bool:
    """True if a race-control message involves our car."""
    if e.car_number == our_car:
        return True
    attrs = e.data.get("attrs") or {}
    cars = attrs.get("cars") or []
    return any(c.get("num") == our_car for c in cars if isinstance(c, dict))