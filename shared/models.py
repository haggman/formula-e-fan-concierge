"""Pydantic models for the Firestore contract between State Writer and Agent.

Mirrors frame schema v1.0 from the simulator (1 Hz JSON frames on Pub/Sub).
Frame schema is documented in the build doc — see the "Schema Reference" section.

Design notes:
- RaceState is the current frame, overwritten in Firestore on every tick.
- Events are written separately to a race_events collection — one doc per event,
  indexed by ts_ns + race_time_s + event_type + car_number for flexible queries.
- All time values in the frame are wall-clock-relative (race_time_s = seconds since
  green flag, ts_ns_wall = nanoseconds since epoch for absolute time).
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ----------------------------------------------------------------------------
# Enums
# ----------------------------------------------------------------------------

class RacePhase(str, Enum):
    """Phase of the race lifecycle."""
    PRE_RACE = "pre_race"
    RACING = "racing"
    SAFETY_CAR = "safety_car"
    FULL_COURSE_YELLOW = "full_course_yellow"
    CHEQUERED = "chequered"


class EventType(str, Enum):
    """Event types in the events[] array of each frame."""
    RACE_CONTROL = "race_control"
    OVERTAKE = "overtake"
    ATTACK_MODE_ACTIVATED = "attack_mode_activated"
    ATTACK_MODE_DEACTIVATED = "attack_mode_deactivated"
    LAP_COMPLETED = "lap_completed"


# ----------------------------------------------------------------------------
# Nested per-car state
# ----------------------------------------------------------------------------

class GPSState(BaseModel):
    """Per-car GPS — WGS84 + heading degrees."""
    lat: float
    lng: float
    heading: float


class EnergyState(BaseModel):
    """Per-car energy state.

    Note: kwh_remaining is computed from 41 kWh budget but FE's actual is
    38.5 kWh — kwh values are ~6.5% high. Agent reasons on percentages.
    """
    pct_remaining: float
    kwh_remaining: float
    pct_used: float


class AttackModeState(BaseModel):
    """Per-car Attack Mode state.

    Scenario: 1=short-first (60+180), 2=even (120+120), 3=long-first (180+60).
    R10 total AM budget is 240s (split across activations per scenario).
    activations_used counts completed activations only — not in-progress.
    """
    active: bool
    activations_used: int
    scenario: int
    remaining_budget_s: float


class CarState(BaseModel):
    """Per-car snapshot at one race-second."""
    car_number: int
    driver_short_name: str
    position: int
    current_lap: int
    speed_kmh: float
    gps: GPSState
    accel_x: float
    accel_y: float
    brake_pct: float
    steer: float  # raw wheel ticks, NOT degrees (~±3300 range)
    yaw_rate: float
    energy: EnergyState
    attack_mode: AttackModeState
    is_retired: bool


# ----------------------------------------------------------------------------
# RaceState — full frame snapshot, overwritten in Firestore per tick
# ----------------------------------------------------------------------------

class RaceState(BaseModel):
    """Current race state. One doc in Firestore at race_states/{race_id}.

    The State Writer overwrites this doc on every Pub/Sub frame. The Agent
    and Frontend read it for "what's happening right now."
    """
    schema_version: str
    race_id: str
    race_time_s: int
    race_duration_s: float
    pct_complete: float
    race_phase: RacePhase
    current_leader_lap: int
    cars: list[CarState]
    # Augmented by State Writer (not in raw frame): wall-clock ns of the tick
    ts_ns_wall: Optional[int] = None

    def car_by_number(self, car_number: int) -> Optional[CarState]:
        """Look up a car by number. Returns None if not found."""
        for car in self.cars:
            if car.car_number == car_number:
                return car
        return None


# ----------------------------------------------------------------------------
# Event — written individually to race_events/{auto-id}
# ----------------------------------------------------------------------------

class Event(BaseModel):
    """A single event occurring at a specific moment in the race.

    State Writer creates one Event doc per item in frame.events[].
    Queried by the agent's get_recent_events tool via Firestore indexes.

    Indexed fields:
      - ts_ns_wall (wall-clock time, supports time-range queries)
      - race_time_s (race-relative time, supports lap-bounded queries)
      - event_type (filter by type)
      - car_number (filter to events involving a specific car)
    """
    event_type: EventType
    ts_ns_wall: int          # wall-clock time the event occurred
    race_time_s: int         # race-relative time (seconds since green flag)
    race_id: str             # in case we ever load multiple races
    car_number: Optional[int] = None  # car the event involves; null for some race_control

    # Type-specific fields — varies by event_type. Stored as a flat dict so
    # Firestore queries can reach in if needed; structured access via model.
    data: dict[str, Any] = Field(default_factory=dict)
