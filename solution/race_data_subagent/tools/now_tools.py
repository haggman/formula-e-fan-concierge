"""Firestore "now" tools for the race-data subagent. [SKELETON — see spec]

Field-wide live-state reads — the subagent's window into "now." Unlike Ch2's
car-13 frame tools, these take a car_number (any car) and also expose the field.
Every response carries race_wall_time_ns so the agent can bound BigQuery.

Shares shared.state_client (the vendored Firestore reader) with the commentator.

  get_field_now() -> FieldNowResponse
      All running cars (position, driver, speed, energy, AM) + race_time_s +
      race_wall_time_ns. The "what's the state of the race right now" call.

  get_car_now(car_number: int) -> CarNowResponse
      One car's live situation (any car). + race_wall_time_ns.

  get_recent_events(seconds_back=30, event_types=None, car_involved=None, limit=50)
      Ported from Ch2 — already field-wide.
"""
from __future__ import annotations


def get_field_now():
    """[SKELETON] Whole-field live snapshot + race_wall_time_ns."""
    raise NotImplementedError("see spec/cx_integration_spike.md + Ch2 frame_tools")


def get_car_now(car_number: int):
    """[SKELETON] One car's live situation (any car) + race_wall_time_ns."""
    raise NotImplementedError("generalize Ch2 get_current_state from #13 to any car")


def get_recent_events(seconds_back=30, event_types=None, car_involved=None, limit=50):
    """[SKELETON] Kept from Ch2 — already field-wide."""
    raise NotImplementedError("port from Ch2 frame_tools.get_recent_events")
