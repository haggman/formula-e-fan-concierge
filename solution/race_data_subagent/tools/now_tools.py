"""Firestore "now" tools for the race-data subagent — reference solution.

Field-wide live-state reads: the subagent's window into "now". Unlike Ch2's
car-13-centric frame tools, these take any car_number and also expose the whole
field. Every response carries `race_wall_time_ns` so the agent can bound every
BigQuery call to the replay's current moment (time-honesty).

Shares shared.state_client (the vendored Firestore reader) with the commentator,
so "now" is read from the same race_states/{race_id} doc the live plane writes.

Three ADK tools (the LLM agent calls these):
  get_field_now()                         whole-field snapshot + race_wall_time_ns
  get_car_now(car_number)                 one car's live situation (any car)
  get_recent_events(...)                  recent events, field-wide, filterable

Plus two helpers used by the DETERMINISTIC first-light path in app.py (no LLM):
  read_now()                              the bare current moment {race_time_s, ...}
  is_future_question(question)            keyword guard for the spoiler refusal

IMPORTS ARE LAZY ON PURPOSE. shared.state_client imports google-cloud-firestore
at module top; keeping that import inside the functions lets app.py's
DETERMINISTIC mode (canned moment, no data plane, no firestore dep) import this
module without pulling Firestore. The same laziness is what makes the local
verification harness runnable with nothing but FastAPI installed.

TIME-HONESTY GUARD (the "AgentEvent" lesson from Ch2): race_wall_time_ns is
derived ONLY from the replay's race_time_s via config.race_time_to_wall_ns —
never from the host's real wall clock. A 2026 timestamp can therefore never
leak in as a BigQuery through_time_ns bound; the upper bound is always the
replay moment and nothing past it.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from ..config import RACE_ID, race_time_to_wall_ns

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal: the shared Firestore reader, imported lazily (see module docstring).
# ---------------------------------------------------------------------------
def _state_client():
    """Return the process-wide StateClient singleton (lazy import).

    Raises if shared.state_client / firestore aren't importable — callers that
    must tolerate a missing data plane (read_now) catch this and fall back to a
    canned moment; the ADK tools let it surface as a tool error.
    """
    from shared.state_client import get_state_client

    return get_state_client()


def _wrap_now(race_time_s: int, source: str) -> dict:
    """Common "now" envelope every response carries."""
    return {
        "race_time_s": int(race_time_s),
        "race_wall_time_ns": race_time_to_wall_ns(int(race_time_s)),
        "now_source": source,
    }


# ---------------------------------------------------------------------------
# ADK tools — the LLM agent calls these for "now" questions.
# ---------------------------------------------------------------------------
def get_field_now() -> dict:
    """Whole-field live snapshot: every running car right now, plus the moment.

    Returns position-sorted cars (number, driver, position, lap, speed, energy %,
    attack mode) and the race-wide state (phase, % complete, leader lap), plus
    race_time_s and race_wall_time_ns. This is the "what's the state of the race
    right now" call — use it for standings, "who's leading", field overview, and
    to learn the current moment before any BigQuery (career/"then") lookup.
    """
    state = _state_client().get_race_state()
    if state is None:
        return {
            "error": f"no live race state for {RACE_ID} yet (data plane not up).",
            **_wrap_now(int(os.environ.get("FE_STUB_RACE_TIME_S", "0")), "unavailable"),
        }

    cars = sorted(
        (c for c in state.cars if not c.is_retired),
        key=lambda c: c.position,
    )
    return {
        "race_phase": state.race_phase.value,
        "pct_complete": round(state.pct_complete, 1),
        "current_leader_lap": state.current_leader_lap,
        "cars": [
            {
                "position": c.position,
                "car_number": c.car_number,
                "driver": c.driver_short_name,
                "current_lap": c.current_lap,
                "speed_kmh": round(c.speed_kmh, 1),
                "energy_pct_remaining": round(c.energy.pct_remaining, 1),
                "attack_mode_active": c.attack_mode.active,
                "attack_activations_used": c.attack_mode.activations_used,
            }
            for c in cars
        ],
        **_wrap_now(state.race_time_s, "firestore"),
    }


def get_car_now(car_number: int) -> dict:
    """One car's live situation right now (ANY car, not just #13), plus the moment.

    Returns that car's position, lap, speed, energy, and attack-mode state, with
    race_time_s and race_wall_time_ns. Use for "how's car N doing right now",
    "what's N's energy", "is N in attack mode". For the whole field use
    get_field_now.
    """
    state = _state_client().get_race_state()
    if state is None:
        return {
            "error": f"no live race state for {RACE_ID} yet (data plane not up).",
            **_wrap_now(int(os.environ.get("FE_STUB_RACE_TIME_S", "0")), "unavailable"),
        }

    car = state.car_by_number(car_number)
    if car is None:
        return {
            "error": f"car {car_number} not found in the current field.",
            **_wrap_now(state.race_time_s, "firestore"),
        }

    return {
        "car_number": car.car_number,
        "driver": car.driver_short_name,
        "position": car.position,
        "current_lap": car.current_lap,
        "speed_kmh": round(car.speed_kmh, 1),
        "is_retired": car.is_retired,
        "energy": {
            "pct_remaining": round(car.energy.pct_remaining, 1),
            "pct_used": round(car.energy.pct_used, 1),
        },
        "attack_mode": {
            "active": car.attack_mode.active,
            "activations_used": car.attack_mode.activations_used,
            "scenario": car.attack_mode.scenario,
            "remaining_budget_s": round(car.attack_mode.remaining_budget_s, 1),
        },
        **_wrap_now(state.race_time_s, "firestore"),
    }


def get_recent_events(
    seconds_back: int = 30,
    event_types: Optional[list[str]] = None,
    car_involved: Optional[int] = None,
    limit: int = 50,
) -> dict:
    """Recent live race events (field-wide), bounded to the current moment.

    Returns events from the last `seconds_back` seconds of race time — overtakes,
    attack-mode activations, race-control messages, lap completions. Optionally
    filter by event_types (e.g. ["overtake","attack_mode_activated"]) and/or a
    single car_involved. Use for "what just happened", "any recent overtakes",
    "is there a safety car". Naturally time-honest: it only sees events at or
    before the current race_time_s.
    """
    client = _state_client()
    state = client.get_race_state()
    if state is None:
        return {
            "events": [],
            "error": f"no live race state for {RACE_ID} yet (data plane not up).",
            **_wrap_now(int(os.environ.get("FE_STUB_RACE_TIME_S", "0")), "unavailable"),
        }

    now_s = state.race_time_s
    events = client.query_events(
        from_race_time_s=max(0, now_s - int(seconds_back)),
        to_race_time_s=now_s,  # never past the current moment — no spoilers
        event_types=event_types,
        car_involved=car_involved,
        limit=limit,
    )
    return {
        "events": [
            {
                "event_type": e.event_type.value,
                "race_time_s": e.race_time_s,
                "car_number": e.car_number,
                "data": e.data,
            }
            for e in events
        ],
        **_wrap_now(now_s, "firestore"),
    }


# ---------------------------------------------------------------------------
# Helpers for the DETERMINISTIC first-light path (app.py, no LLM, no creds).
# ---------------------------------------------------------------------------
def read_now() -> dict:
    """The bare current moment: {race_time_s, race_wall_time_ns, now_source}.

    Tries the live plane; on ANY failure (no firestore dep, no data plane, no
    doc yet) falls back to a canned moment (FE_STUB_RACE_TIME_S, default 900s)
    so the CX wire can be proven end to end before the simulator is up. The
    CX-facing contract is identical either way — only now_source changes
    ("firestore" vs "canned").
    """
    try:
        state = _state_client().get_race_state()
        if state is not None:
            return _wrap_now(state.race_time_s, "firestore")
        logger.warning("race_states/%s not present yet — canned moment", RACE_ID)
    except Exception as e:  # noqa: BLE001 — first-light must never break the wire
        logger.warning("Firestore 'now' read failed (%s) — canned moment", e)

    canned = int(float(os.environ.get("FE_STUB_RACE_TIME_S", "900")))
    return _wrap_now(canned, "canned")


# Cheap heuristic for the deterministic time-honesty negative check. The LLM
# subagent enforces this mechanically (the through_time_ns bound) and by prompt;
# the deterministic path proves the wire refuses a "who wins?" question with no
# model in the loop. Keep in sync with the prompt's refusal doctrine.
_FUTURE_MARKERS = (
    "who wins", "who win", "who won", "winner", "win the race", "going to win",
    "final result", "final results", "podium", "who finishes", "who will finish",
    "end of the race", "predict", "what happens next", "rest of the race",
    "who will win", "final standings", "final position",
)


def is_future_question(question: str) -> bool:
    """True if the question asks about something after the current moment."""
    q = (question or "").lower()
    return any(m in q for m in _FUTURE_MARKERS)
