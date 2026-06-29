"""Significance scorer — decides WHEN the commentator should speak.

PURE AND DETERMINISTIC: no I/O, no clocks, no randomness. Same inputs →
same output, always. The caller (the commentator loop / the local harness)
owns polling, debounce, and lap-change scheduling. Code decides *when* to
speak; the LLM decides *what* to say.

RE-AIMED FROM CH2 (see spec/frame_tools_scorer_reaim.md): Ch2's race engineer
scored from car #13's first-person "our car" POV (SCORE_WE_*, SCORE_OUR_AM_*,
RC_INVOLVES_US). The commentator is a third-person FIELD broadcaster, so the
weights are now event-significance constants that apply to ANY car, plus a
boost when the event involves the fan's SELECTED car. With no selection the
scorer ranks pure field significance (lead battles, big swings, AM clusters,
race control); with a selection, the same events near that car bubble to the
top — commentary "follows what you're watching" without going blind to the
rest of the field.

Three trigger types in the system:
  - EVENT_REACTION: produced HERE when something significant happens
  - LAP_SUMMARY:    scheduled by the CALLER on lap change (not scored)
  - QA:             user-initiated, never scored
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from shared.models import Event, EventType, RaceState

# ============================================================================
# Tunable weights — field significance, not "our car"
# ============================================================================

DEFAULT_THRESHOLD = 60          # candidates below this never fire

SCORE_OVERTAKE = 70             # any completed pass
SCORE_AM_ACTIVATED = 60         # any car takes Attack Mode
SCORE_AM_DEACTIVATED = 50       # only emitted for the selected car
SCORE_AM_CLUSTER = 75           # >= AM_CLUSTER_MIN activations in lookback
AM_CLUSTER_MIN = 3
SCORE_POSITION_SWING_BASE = 55  # any car gaining/losing >= POSITION_SWING_MIN places
POSITION_SWING_MIN = 2          # net positions vs the caller's previous check

# Boosts layered on top of the base significance of an event.
SELECTED_CAR_BOOST = 25         # event involves the fan's selected car (or its battle)
LEAD_BATTLE_BOOST = 15          # event at/near the front (P1..PODIUM_MAX)
PODIUM_MAX = 3                  # "near the lead" cutoff

# When a SELECTED-car event reaches this (boosted) score, the broadcast must
# not skip it — the fan is watching that car. Field-critical race control has
# its own must-say path below (safety car / red / chequered).
SELECTED_CAR_MUST_SAY_MIN = 80

# Race control severity by category prefix (first match wins). KEPT from Ch2.
RC_SEVERITY = [
    ("flag.chequered", 95),
    ("safety_car", 95),
    ("flag.red", 95),
    ("flag.double_yellow", 70),
    ("flag.yellow", 65),
    ("penalty", 60),
    ("incident", 45),
    ("flag.green", 55),
    ("pit", 30),
]
RC_MUST_SAY_MIN = 88            # safety car / red / chequered → cannot stay silent


class TriggerType(str, Enum):
    EVENT_REACTION = "event_reaction"
    LAP_SUMMARY = "lap_summary"
    QA = "qa"


class TriggerCandidate(BaseModel):
    """One scored reason to speak. Caller fires the best one above threshold.

    must_say marks moments the commentator cannot stay silent on: field-critical
    race control (safety car / red / chequered), and high-significance events
    involving the fan's selected car. The scorer CLASSIFIES; the caller decides
    what must_say buys (a shorter debounce, typically).
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
    selected_car: Optional[int] = None,
    recent_am_activations: int = 0,
    prev_positions: Optional[dict[int, int]] = None,
) -> list[TriggerCandidate]:
    """Score the current moment field-wide. Returns candidates best-first.

    Args:
      state: current RaceState.
      new_events: events NOT YET SCORED (since the caller's last check). Per-event
        rules fire on these only, so the caller never double-fires.
      selected_car: the car the fan is watching, or None for pure field-wide.
        Events involving this car (or its immediate battle) get SELECTED_CAR_BOOST.
      recent_am_activations: count of field AM activations in the caller's lookback
        window (~30 race-seconds) — feeds the cluster rule.
      prev_positions: {car_number: position} at the caller's previous check, for
        field-wide position-swing detection. None on the first check.
    """
    candidates: list[TriggerCandidate] = []

    for e in new_events:
        payload = {
            "event_type": e.event_type.value,
            "race_time_s": e.race_time_s,
            "car_number": e.car_number,
            "data": e.data,
        }

        if e.event_type == EventType.OVERTAKE:
            candidates.extend(_score_overtake(state, e, payload, selected_car))

        elif e.event_type == EventType.ATTACK_MODE_ACTIVATED:
            candidates.extend(_score_am_activated(state, e, payload, selected_car))

        elif e.event_type == EventType.ATTACK_MODE_DEACTIVATED:
            candidates.extend(_score_am_deactivated(e, payload, selected_car))

        elif e.event_type == EventType.RACE_CONTROL:
            candidates.extend(_score_race_control(e, payload, selected_car))

    # Field-wide AM cluster (needs the caller's lookback count, not new_events)
    if recent_am_activations >= AM_CLUSTER_MIN:
        candidates.append(TriggerCandidate(
            trigger_type=TriggerType.EVENT_REACTION,
            score=SCORE_AM_CLUSTER,
            reason=(f"attack mode cluster: {recent_am_activations} activations "
                    "across the field in the last half minute"),
        ))

    # Field-wide net position swings since the caller's last check
    candidates.extend(_score_position_swings(state, prev_positions, selected_car))

    candidates.sort(key=lambda c: (c.must_say, c.score), reverse=True)
    return candidates


# ============================================================================
# Per-event scorers
# ============================================================================


def _score_overtake(state, e, payload, selected_car) -> list[TriggerCandidate]:
    other = str(e.data.get("participant"))
    subject = e.car_number
    if subject is None:
        return []
    if other == str(subject):
        # Source-data glitch: one record has subject == other (a car
        # "overtaking itself"). Known artifact — never score it.
        return []

    try:
        other_num = int(other)
    except (TypeError, ValueError):
        other_num = None

    subject_gained = e.data.get("position_change", 0) < 0
    if subject_gained:
        winner, loser = subject, other_num
    else:
        winner, loser = other_num, subject
    reason = (f"car {winner} is through on car {loser}"
              if winner is not None and loser is not None
              else f"overtake involving car {subject}")

    sc = SCORE_OVERTAKE
    if _near_lead(state, subject, other_num):
        sc += LEAD_BATTLE_BOOST
    involves_selected = selected_car is not None and selected_car in (subject, other_num)
    if involves_selected:
        sc += SELECTED_CAR_BOOST

    return [TriggerCandidate(
        trigger_type=TriggerType.EVENT_REACTION,
        score=sc,
        reason=reason,
        must_say=involves_selected and sc >= SELECTED_CAR_MUST_SAY_MIN,
        events=[payload],
    )]


def _score_am_activated(state, e, payload, selected_car) -> list[TriggerCandidate]:
    car = e.car_number
    if car is None:
        return []
    driver = _driver_of(state, car)
    sc = SCORE_AM_ACTIVATED
    if _near_lead(state, car):
        sc += LEAD_BATTLE_BOOST
    # "Involves" the fan's battle if it's the selected car OR a car right
    # next to it (a rival arming 50 kW is news for whoever the fan watches).
    involves_selected = selected_car is not None and (
        car == selected_car or _is_neighbor(state, car, selected_car)
    )
    if involves_selected:
        sc += SELECTED_CAR_BOOST
    label = f"car {car}" + (f" ({driver})" if driver else "")
    if selected_car is not None and car != selected_car and involves_selected:
        reason = f"{label} (right by the car you're watching) took attack mode"
    else:
        reason = f"{label} took attack mode"
    return [TriggerCandidate(
        trigger_type=TriggerType.EVENT_REACTION,
        score=sc,
        reason=reason,
        must_say=involves_selected and sc >= SELECTED_CAR_MUST_SAY_MIN,
        events=[payload],
    )]


def _score_am_deactivated(e, payload, selected_car) -> list[TriggerCandidate]:
    # AM ending is a quiet beat field-wide; only call it for the watched car.
    if selected_car is None or e.car_number != selected_car:
        return []
    return [TriggerCandidate(
        trigger_type=TriggerType.EVENT_REACTION,
        score=SCORE_AM_DEACTIVATED + SELECTED_CAR_BOOST,
        reason=f"car {e.car_number}'s attack mode is done",
        events=[payload],
    )]


def _score_race_control(e, payload, selected_car) -> list[TriggerCandidate]:
    category = str(e.data.get("category", ""))
    text = str(e.data.get("text", ""))
    sev = next((s for prefix, s in RC_SEVERITY if category.startswith(prefix)), 0)
    if sev <= 0:
        return []
    if selected_car is not None and _rc_names_car(e, selected_car):
        sev = min(100, sev + SELECTED_CAR_BOOST)
    return [TriggerCandidate(
        trigger_type=TriggerType.EVENT_REACTION,
        score=sev,
        reason=f"race control: {text}" if text else f"race control: {category}",
        must_say=sev >= RC_MUST_SAY_MIN,
        events=[payload],
    )]


def _score_position_swings(state, prev_positions, selected_car) -> list[TriggerCandidate]:
    if not prev_positions:
        return []
    out: list[TriggerCandidate] = []
    for car in state.cars:
        if car.is_retired:
            continue
        prev = prev_positions.get(car.car_number)
        if prev is None:
            continue
        delta = prev - car.position  # positive = gained places
        if abs(delta) < POSITION_SWING_MIN:
            continue
        sc = SCORE_POSITION_SWING_BASE + 5 * (abs(delta) - 1)
        if car.position <= PODIUM_MAX or prev <= PODIUM_MAX:
            sc += LEAD_BATTLE_BOOST
        involves_selected = selected_car is not None and car.car_number == selected_car
        if involves_selected:
            sc += SELECTED_CAR_BOOST
        driver = car.driver_short_name
        out.append(TriggerCandidate(
            trigger_type=TriggerType.EVENT_REACTION,
            score=sc,
            reason=(f"car {car.car_number}"
                    + (f" ({driver})" if driver else "")
                    + f" {'gained' if delta > 0 else 'lost'} {abs(delta)} places "
                      f"(P{prev} -> P{car.position})"),
            must_say=involves_selected and sc >= SELECTED_CAR_MUST_SAY_MIN,
        ))
    return out


# ============================================================================
# Helpers
# ============================================================================


def _driver_of(state: RaceState, car_number: Optional[int]) -> Optional[str]:
    if car_number is None:
        return None
    car = state.car_by_number(car_number)
    return car.driver_short_name if car else None


def _near_lead(state: RaceState, *car_numbers: Optional[int]) -> bool:
    """True if any of the given cars is currently at/near the front (P1..PODIUM_MAX)."""
    for n in car_numbers:
        if n is None:
            continue
        car = state.car_by_number(n)
        if car and not car.is_retired and car.position <= PODIUM_MAX:
            return True
    return False


def _is_neighbor(state: RaceState, car_a: Optional[int], car_b: Optional[int]) -> bool:
    """True if car_a and car_b are running directly next to each other right now.

    Symmetric (unlike Ch2's us-anchored version): any two cars.
    """
    if car_a is None or car_b is None or car_a == car_b:
        return False
    a = state.car_by_number(car_a)
    b = state.car_by_number(car_b)
    if a is None or b is None or a.is_retired or b.is_retired:
        return False
    return abs(a.position - b.position) == 1


def _rc_names_car(e: Event, car: Optional[int]) -> bool:
    """True if a race-control message involves the given car."""
    if car is None:
        return False
    if e.car_number == car:
        return True
    attrs = e.data.get("attrs") or {}
    cars = attrs.get("cars") or []
    return any(c.get("num") == car for c in cars if isinstance(c, dict))
