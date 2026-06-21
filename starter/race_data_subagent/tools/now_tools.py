"""Firestore "now" tools — STARTER.

Build the field-wide live-state reads (the subagent's window into "now"). Every
response must carry `race_wall_time_ns` (from config.race_time_to_wall_ns) so the
agent can bound BigQuery to the current moment.

KEEP IMPORTS LAZY (import shared.state_client / firestore INSIDE the functions),
so app.py's DETERMINISTIC mode can import this module without the Firestore dep.

Build these (see solution/race_data_subagent/tools/now_tools.py):

  ADK tools (the LLM agent calls these):
    get_field_now() -> dict
        Whole-field snapshot: running cars sorted by position (number, driver,
        position, lap, speed, energy %, attack mode) + race phase + race_time_s +
        race_wall_time_ns.
    get_car_now(car_number: int) -> dict
        One car's live situation (ANY car) + race_wall_time_ns.
    get_recent_events(seconds_back=30, event_types=None, car_involved=None,
                      limit=50) -> dict
        Recent events, field-wide, capped at the current moment (no spoilers).

  Helpers app.py's deterministic mode imports:
    read_now() -> dict
        {race_time_s, race_wall_time_ns, now_source}; fall back to a canned
        moment (FE_STUB_RACE_TIME_S) if the data plane isn't up.
    is_future_question(question: str) -> bool
        Keyword guard for the spoiler refusal.

Read from shared.state_client (get_state_client(); RaceState/Event in
shared.models) — the same Firestore the commentator reads.
"""
from __future__ import annotations

# from ..config import RACE_ID, race_time_to_wall_ns

# TODO(student): implement get_field_now, get_car_now, get_recent_events,
#                read_now, is_future_question (see the solution for reference).
