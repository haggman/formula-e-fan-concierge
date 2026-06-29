# ============================================================================
# GIVEN INFRASTRUCTURE — you do NOT need to edit or read this file in depth.
# It is the same field-wide tooling the reference uses. Your build is in
# prompts.py (the persona) and agent.py (wiring). See README.md.
# ============================================================================
"""Trigger snapshot builder — the authoritative 'moment' handed to the
commentator in proactive broadcast prompts.

RE-AIM of Ch2's race_engineer/snapshot.py: that one pinned ONE car (#13) and
its neighbors. The commentator is field-wide, so the snapshot pins the FIELD
(the leading order) plus, when the fan has selected a car, a focus block for
that car's battle. Used by the local harness and the commentator loop.

Lives in the agent package because it depends on agent config (the time bridge).
"""
from __future__ import annotations

from typing import Optional

from starter.commentator.config import race_time_to_wall_ns
from shared.models import RaceState

# How many cars from the front to pin in the snapshot. Enough to ground a
# field call without flooding the prompt.
LEADERS_IN_SNAPSHOT = 6


def snapshot_dict(state: RaceState, selected_car: Optional[int] = None) -> dict:
    """Compact authoritative snapshot for the trigger prompt.

    Pins the leading order and (if a car is selected) that car plus its nearest
    running neighbours, so the agent narrates the moment the trigger fired and
    does not re-fetch a world that has moved on at replay speed.
    """
    running = sorted(
        (c for c in state.cars if not c.is_retired), key=lambda c: c.position
    )

    def brief(c):
        return None if c is None else {
            "car": c.car_number,
            "driver": c.driver_short_name,
            "position": c.position,
            "speed_kmh": round(c.speed_kmh, 0),
            "am_active": c.attack_mode.active,
            "am_activations_used": c.attack_mode.activations_used,
        }

    snap = {
        "race_time_s": state.race_time_s,
        "race_wall_time_ns": race_time_to_wall_ns(state.race_time_s),
        "race_phase": state.race_phase.value,
        "current_leader_lap": state.current_leader_lap,
        "leaders": [brief(c) for c in running[:LEADERS_IN_SNAPSHOT]],
        "running_count": len(running),
        "selected_car": selected_car,
        "focus": None,
    }

    if selected_car is not None:
        idx = next(
            (i for i, c in enumerate(running) if c.car_number == selected_car), None
        )
        if idx is not None:
            ahead = running[idx - 1] if idx > 0 else None
            behind = running[idx + 1] if idx + 1 < len(running) else None
            snap["focus"] = {
                "selected": brief(running[idx]),
                "car_ahead": brief(ahead),
                "car_behind": brief(behind),
            }

    return snap
