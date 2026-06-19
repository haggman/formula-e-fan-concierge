"""Field-wide live-state tools for the commentator. [SKELETON — see spec]

RE-AIM of Ch2's solution/race_engineer/tools/frame_tools.py, which was written
from car #13's "our car" POV (get_current_state returned ONE car's situation).
The commentator needs the WHOLE field, with an optional focus on the selected car.

Full conversion spec: spec/frame_tools_scorer_reaim.md. Summary of the new surface:

  get_field_state(selected_car: int | None = None) -> FieldStateResponse
      Replaces get_current_state. Returns every running car (position, driver,
      speed, energy, AM) sorted by position. If selected_car is given, also
      returns a `focus` block: that car plus its nearest car ahead/behind and
      the gap — the "battle" the commentary narrows to.

  get_recent_events(seconds_back=30, event_types=None, car_involved=None, limit=50)
      Unchanged in shape from Ch2 (already field-wide — it filters by car only
      when asked). Kept as-is.

  get_events_in_range(from_s, to_s, event_types=None, car_involved=None, limit=100)
      Unchanged from Ch2.

  get_field_am_status() -> FieldAmStatusResponse
      Already field-wide in Ch2 (three buckets across the field). Kept as-is; drop
      nothing.

Time bridge: each state/AM response keeps `race_wall_time_ns` for consistency,
though the commentator itself does not query BigQuery.

Source: shared.state_client (vendored Firestore reader), shared.models.
"""
from __future__ import annotations

# Implementation deferred to the build conversation. See the spec for the exact
# response models (FieldStateResponse with a `cars: list[CarLine]` and optional
# `focus: FocusBlock`) and the field-wide rewrite of get_current_state.


def get_field_state(selected_car=None):
    """[SKELETON] Whole-field snapshot, with optional focus on selected_car."""
    raise NotImplementedError("see spec/frame_tools_scorer_reaim.md")


def get_recent_events(seconds_back=30, event_types=None, car_involved=None, limit=50):
    """[SKELETON] Kept from Ch2 — already field-wide."""
    raise NotImplementedError("port from Ch2 frame_tools.get_recent_events")


def get_events_in_range(from_race_time_s, to_race_time_s, event_types=None,
                        car_involved=None, limit=100):
    """[SKELETON] Kept from Ch2."""
    raise NotImplementedError("port from Ch2 frame_tools.get_events_in_range")


def get_field_am_status():
    """[SKELETON] Kept from Ch2 — already field-wide."""
    raise NotImplementedError("port from Ch2 frame_tools.get_field_am_status")
