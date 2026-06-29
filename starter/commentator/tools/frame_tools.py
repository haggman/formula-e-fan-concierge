# ============================================================================
# GIVEN INFRASTRUCTURE — you do NOT need to edit or read this file in depth.
# It is the same field-wide tooling the reference uses. Your build is in
# prompts.py (the persona) and agent.py (wiring). See README.md.
# ============================================================================
"""Field-wide live-state tools the commentator agent calls during reasoning.

These read the live race state from Firestore (populated by the State Writer
from Pub/Sub frames). The commentator narrates the WHOLE field, so the surface
is field-wide — unlike Ch2's race engineer, which framed everything around
"our car #13."

Tools:
  - get_field_state(selected_car=None) — every running car, position-sorted; plus
      an optional `focus` block (the selected car + its nearest battle) when the
      fan has clicked a car.
  - get_recent_events — events in the last N seconds, optionally filtered.
  - get_events_in_range — events in a specific race-time window.
  - get_field_am_status — Attack Mode activity across the field.

All tools return Pydantic models that ADK serializes for Gemini.

RE-AIM (see spec/frame_tools_scorer_reaim.md): Ch2's get_current_state returned
ONE car's situation (car #13) and had OUR_CAR_NUMBER / _require_our_car baked in.
Those are GONE — no car is special at the data layer. "Special" is a runtime
`selected_car` argument that adds a focus block. get_recent_events,
get_events_in_range, and get_field_am_status were already field-wide in Ch2 and
are ported unchanged.

event_types parameters: Gemini passes function args as JSON, so enum-typed
params arrive as plain strings and ADK does NOT coerce them. The signatures take
list[str] and coerce internally (with a clear error listing valid values).

Time bridge: get_field_state and get_field_am_status keep race_wall_time_ns —
the current moment in the ORIGINAL 2024 race's wall clock. The commentator does
not query BigQuery, but the field is kept for repo consistency (the race-data
subagent's now_tools rely on the identical clock).

Source: shared.state_client (vendored Firestore reader), shared.models.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from starter.commentator.config import AM_SCENARIOS, race_time_to_wall_ns
from shared.models import CarState, Event, EventType, RaceState
from shared.state_client import get_state_client


# ============================================================================
# Tool response models
# ============================================================================


class CarLine(BaseModel):
    """One car's line in the field snapshot — compact, uniform for every car."""
    car_number: int
    driver_short_name: str
    position: int
    current_lap: int
    speed_kmh: float
    energy_pct_remaining: float
    am_active: bool
    am_activations_used: int
    am_scenario: int
    am_remaining_budget_s: float
    is_retired: bool = False


class FocusBlock(BaseModel):
    """The 'battle' the commentary narrows to when a car is selected.

    The selected car plus the nearest RUNNING car ahead and behind. Gaps are
    expressed in POSITIONS (we have no time-gap telemetry — never state seconds).
    A gap > 1 means cars between have retired.
    """
    selected: CarLine
    car_ahead: Optional[CarLine] = None
    car_behind: Optional[CarLine] = None
    gap_ahead_positions: Optional[int] = None
    gap_behind_positions: Optional[int] = None


class FieldStateResponse(BaseModel):
    """Whole-field snapshot right now, with an optional focus on the selected car."""
    cars: list[CarLine]                       # every running car, position-sorted
    focus: Optional[FocusBlock] = None        # set only when selected_car is given
    selected_car: Optional[int] = None
    race_phase: str
    race_time_s: int
    current_leader_lap: int
    race_wall_time_ns: int = Field(
        description="Current moment in the original 2024 race's wall clock "
                    "(ns since epoch). Repo-wide canonical clock; the commentator "
                    "does not query BigQuery."
    )


class AgentEvent(BaseModel):
    """Agent-facing view of an Event — reasoning-relevant fields only.

    Excludes ts_ns_wall (the replay machine's wall clock) and race_id; events
    expose race_time_s only.
    """
    event_type: EventType
    race_time_s: int
    car_number: Optional[int] = None
    data: dict = Field(default_factory=dict)

    @classmethod
    def from_event(cls, e: Event) -> "AgentEvent":
        return cls(
            event_type=e.event_type,
            race_time_s=e.race_time_s,
            car_number=e.car_number,
            data=e.data,
        )


class RecentEventsResponse(BaseModel):
    """List of events matching a query, newest first."""
    events: list[AgentEvent]
    count: int
    filters_applied: dict = Field(default_factory=dict)


class AmCarStatus(BaseModel):
    """One car's AM situation in the field-wide summary."""
    car_number: int
    driver_short_name: str
    position: int
    active_now: bool
    activations_used: int
    scenario: int
    remaining_budget_s: float


class FieldAmStatusResponse(BaseModel):
    """Field-wide Attack Mode snapshot."""
    active_now: list[AmCarStatus]              # cars currently in AM
    used_at_least_one: list[AmCarStatus]       # used >=1 activation
    untouched: list[AmCarStatus]               # zero activations yet
    scenario_distribution: dict[int, int]      # scenario -> car count
    race_phase: str
    race_time_s: int
    race_wall_time_ns: int = Field(
        description="Current moment in the original 2024 race's wall clock "
                    "(ns since epoch)."
    )


# ============================================================================
# Tool implementations
# ============================================================================


def get_field_state(selected_car: Optional[int] = None) -> FieldStateResponse:
    """Get the whole field's live snapshot right now, position-sorted.

    Returns every running car (number, driver, position, lap, speed, energy,
    Attack Mode). This is the FIRST call for any "what's happening now" reasoning
    — it gives the commentator the full field to narrate.

    If `selected_car` is given (the fan clicked a car in the UI), the response
    also includes a `focus` block: that car plus the nearest running car ahead
    and behind, so the commentary can narrow onto that battle. Leave it None to
    cover the whole field.

    Source: Firestore race_states doc, cached 1s.
    """
    state = _require_state()
    running = sorted(
        (c for c in state.cars if not c.is_retired),
        key=lambda c: c.position,
    )
    cars = [_car_line(c) for c in running]

    focus: Optional[FocusBlock] = None
    if selected_car is not None:
        focus = _build_focus(running, selected_car)

    return FieldStateResponse(
        cars=cars,
        focus=focus,
        selected_car=selected_car,
        race_phase=state.race_phase.value,
        race_time_s=state.race_time_s,
        current_leader_lap=state.current_leader_lap,
        race_wall_time_ns=race_time_to_wall_ns(state.race_time_s),
    )


def get_recent_events(
    seconds_back: int = 30,
    event_types: Optional[list[str]] = None,
    car_involved: Optional[int] = None,
    limit: int = 50,
) -> RecentEventsResponse:
    """Events within the last N seconds of race time.

    Optionally filter by event type(s) and/or by a car involved. Returns newest
    first. Use this for "what just happened?" reasoning.

    Args:
      seconds_back: Look back this many seconds from the current race_time_s.
      event_types: Only events of these types. Valid values: "race_control",
        "overtake", "attack_mode_activated", "attack_mode_deactivated",
        "lap_completed".
      car_involved: Only events with car_number = this value.
      limit: Cap on number of events returned (default 50).
    """
    types = _coerce_event_types(event_types)
    state = _require_state()
    to_race_time = state.race_time_s
    from_race_time = max(0, to_race_time - seconds_back)

    client = get_state_client()
    events = client.query_events(
        from_race_time_s=from_race_time,
        to_race_time_s=to_race_time,
        event_types=types,
        car_involved=car_involved,
        limit=limit,
    )

    agent_events = [AgentEvent.from_event(e) for e in events]
    return RecentEventsResponse(
        events=agent_events,
        count=len(agent_events),
        filters_applied={
            "from_race_time_s": from_race_time,
            "to_race_time_s": to_race_time,
            "event_types": [t.value for t in types] if types else None,
            "car_involved": car_involved,
            "limit": limit,
        },
    )


def get_events_in_range(
    from_race_time_s: int,
    to_race_time_s: int,
    event_types: Optional[list[str]] = None,
    car_involved: Optional[int] = None,
    limit: int = 100,
) -> RecentEventsResponse:
    """Events in a specific race-time window.

    Use for "what happened since the safety car" or a specific stretch of the
    race. Same shape as get_recent_events but an absolute window.

    Args:
      from_race_time_s: Window start (race-relative seconds, inclusive).
      to_race_time_s: Window end (race-relative seconds, inclusive).
      event_types: Only events of these types. Valid values: "race_control",
        "overtake", "attack_mode_activated", "attack_mode_deactivated",
        "lap_completed".
      car_involved: Only events with car_number = this value.
      limit: Cap on number of events returned (default 100).
    """
    types = _coerce_event_types(event_types)
    client = get_state_client()
    events = client.query_events(
        from_race_time_s=from_race_time_s,
        to_race_time_s=to_race_time_s,
        event_types=types,
        car_involved=car_involved,
        limit=limit,
    )
    agent_events = [AgentEvent.from_event(e) for e in events]
    return RecentEventsResponse(
        events=agent_events,
        count=len(agent_events),
        filters_applied={
            "from_race_time_s": from_race_time_s,
            "to_race_time_s": to_race_time_s,
            "event_types": [t.value for t in types] if types else None,
            "car_involved": car_involved,
            "limit": limit,
        },
    )


def get_field_am_status() -> FieldAmStatusResponse:
    """Snapshot of Attack Mode activity across the whole field.

    Returns three buckets (active now / used at least one / untouched) and the
    scenario distribution. Use for "who's got Attack Mode in hand?" reasoning and
    to resolve driver codes to car numbers (it lists every running car).
    """
    state = _require_state()

    active_now: list[AmCarStatus] = []
    used: list[AmCarStatus] = []
    untouched: list[AmCarStatus] = []
    scenario_dist: dict[int, int] = {}

    for car in state.cars:
        if car.is_retired:
            continue
        status = AmCarStatus(
            car_number=car.car_number,
            driver_short_name=car.driver_short_name,
            position=car.position,
            active_now=car.attack_mode.active,
            activations_used=car.attack_mode.activations_used,
            scenario=car.attack_mode.scenario,
            remaining_budget_s=round(car.attack_mode.remaining_budget_s, 1),
        )
        if car.attack_mode.active:
            active_now.append(status)
        elif car.attack_mode.activations_used > 0:
            used.append(status)
        else:
            untouched.append(status)
        scenario_dist[car.attack_mode.scenario] = (
            scenario_dist.get(car.attack_mode.scenario, 0) + 1
        )

    for bucket in (active_now, used, untouched):
        bucket.sort(key=lambda s: s.position)

    return FieldAmStatusResponse(
        active_now=active_now,
        used_at_least_one=used,
        untouched=untouched,
        scenario_distribution=scenario_dist,
        race_phase=state.race_phase.value,
        race_time_s=state.race_time_s,
        race_wall_time_ns=race_time_to_wall_ns(state.race_time_s),
    )


# ============================================================================
# Helpers
# ============================================================================


def _car_line(c: CarState) -> CarLine:
    return CarLine(
        car_number=c.car_number,
        driver_short_name=c.driver_short_name,
        position=c.position,
        current_lap=c.current_lap,
        speed_kmh=round(c.speed_kmh, 1),
        energy_pct_remaining=round(c.energy.pct_remaining, 2),
        am_active=c.attack_mode.active,
        am_activations_used=c.attack_mode.activations_used,
        am_scenario=c.attack_mode.scenario,
        am_remaining_budget_s=round(c.attack_mode.remaining_budget_s, 1),
        is_retired=c.is_retired,
    )


def _build_focus(
    running_sorted: list[CarState], selected_car: int
) -> Optional[FocusBlock]:
    """The selected car + nearest running car ahead/behind, with position gaps."""
    idx = next(
        (i for i, c in enumerate(running_sorted) if c.car_number == selected_car),
        None,
    )
    if idx is None:
        # Selected car isn't running (retired, or not in the field) — no focus.
        return None

    sel = running_sorted[idx]
    ahead = running_sorted[idx - 1] if idx > 0 else None
    behind = running_sorted[idx + 1] if idx + 1 < len(running_sorted) else None

    return FocusBlock(
        selected=_car_line(sel),
        car_ahead=_car_line(ahead) if ahead else None,
        car_behind=_car_line(behind) if behind else None,
        gap_ahead_positions=(sel.position - ahead.position) if ahead else None,
        gap_behind_positions=(behind.position - sel.position) if behind else None,
    )


def _coerce_event_types(
    event_types: Optional[list[str]],
) -> Optional[list[EventType]]:
    """Coerce string event types (as Gemini sends them) to EventType enums.

    ADK passes function args straight from JSON — enum coercion is on us.
    Accepts EventType instances too (our own tests pass them directly).
    """
    if not event_types:
        return None
    coerced: list[EventType] = []
    for t in event_types:
        if isinstance(t, EventType):
            coerced.append(t)
            continue
        try:
            coerced.append(EventType(t))
        except ValueError:
            valid = ", ".join(e.value for e in EventType)
            raise ValueError(f"Unknown event type {t!r}. Valid values: {valid}")
    return coerced


def _require_state() -> RaceState:
    """Fetch RaceState, raise if it doesn't exist (e.g. before first frame)."""
    state = get_state_client().get_race_state()
    if state is None:
        raise RuntimeError(
            "No RaceState in Firestore yet. The simulator may not be running, "
            "or the State Writer hasn't received its first frame."
        )
    return state
