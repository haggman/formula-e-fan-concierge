"""Validate the commentator's FIELD-WIDE frame tools against Firestore.

THE FRAME-TOOLS VALIDATOR (Tier B: prove the GIVEN tools against the live
replay). Resolved through the AGENT_PACKAGE seam (shared/agent_pkg.py), so with
activate.sh defaults this tests starter/commentator/tools/frame_tools.py — which
ships COMPLETE (given infrastructure): every section should print ✓ as-is, and a
✗ means environment (simulator not running, stale Firestore), not code. To
validate the reference instead:
    AGENT_PACKAGE=solution.commentator python scripts/test_frame_tools.py --live

RE-AIM from Ch2: the engineer's get_current_state (one car, #13) is gone. The
commentator surface is field-wide — get_field_state returns the WHOLE field and,
given a selected car, a focus block (that car + nearest ahead/behind + position
gaps). This validator asserts the field shape and the focus block.

Two modes:

SEED MODE (default) — run against the canonical static sample frame:
    python scripts/seed_test_state.py
    python scripts/test_frame_tools.py
  Asserts the seeded field (DAC car 13 present, safety car phase).

LIVE MODE — run against a live simulator replay:
    python scripts/test_frame_tools.py --live
  Structural sanity, query mechanics, and data-quality invariants.

Pure-logic checks that need no Firestore at all live in
scripts/verify_commentator_offline.py.
"""
from __future__ import annotations

from shared.script_env import require_venv
require_venv()

import argparse
import sys

from shared.agent_pkg import AGENT_PACKAGE, agent_module
from shared.models import EventType

# Resolve the frame tools from the ACTIVE commentator package — the same import
# path ADK uses when the agent calls them.
_ft = agent_module("tools.frame_tools")
get_field_state = _ft.get_field_state
get_recent_events = _ft.get_recent_events
get_events_in_range = _ft.get_events_in_range
get_field_am_status = _ft.get_field_am_status

# A car known to run the whole Berlin R10 replay — used to exercise the focus
# block and the per-car event filter. (Car 13 = DAC, the R10 winner.)
FOCUS_CAR = 13


def header(label: str) -> None:
    print(f"\n── {label} ──")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true",
                        help="validate against a live replay instead of the seed frame")
    args = parser.parse_args()
    live = args.live
    mode = "LIVE replay" if live else "SEED frame"
    print(f"Mode: {mode}  |  Package: {AGENT_PACKAGE}")

    fails = 0
    race_now = None

    # ------------------------------------------------------------------
    header("get_field_state (whole field)")
    try:
        resp = get_field_state()
        race_now = resp.race_time_s
        print(f"  {len(resp.cars)} running cars, phase {resp.race_phase}, "
              f"t={resp.race_time_s}s, leader on lap {resp.current_leader_lap}")
        for c in resp.cars[:6]:
            print(f"    P{c.position} #{c.car_number} ({c.driver_short_name}) "
                  f"{c.speed_kmh} km/h, {c.energy_pct_remaining}% energy, "
                  f"AM active={c.am_active} used={c.am_activations_used}")

        assert len(resp.cars) >= 20, f"expected ~21-22 running cars, got {len(resp.cars)}"
        positions = [c.position for c in resp.cars]
        assert positions == sorted(positions), "cars must be position-sorted"
        assert resp.focus is None, "focus must be None when no car is selected"
        assert resp.race_wall_time_ns > 0, "missing race_wall_time_ns"
        if not live:
            assert any(c.car_number == 13 and c.driver_short_name == "DAC"
                       for c in resp.cars), "expected car 13 (DAC) in the seeded field"
            assert resp.race_phase == "safety_car", "expected safety_car phase (seed)"
        print("  ✓ field shape sane")
    except Exception as e:
        print(f"  ✗ FAILED: {type(e).__name__}: {e}")
        fails += 1

    # ------------------------------------------------------------------
    header(f"get_field_state(selected_car={FOCUS_CAR}) (focus block)")
    try:
        resp = get_field_state(selected_car=FOCUS_CAR)
        f = resp.focus
        assert f is not None, "expected a focus block when a car is selected"
        assert f.selected.car_number == FOCUS_CAR, "focus.selected must be the chosen car"
        print(f"    focus on #{f.selected.car_number} ({f.selected.driver_short_name}) "
              f"P{f.selected.position}")
        if f.car_ahead:
            print(f"      ahead:  #{f.car_ahead.car_number} ({f.car_ahead.driver_short_name}) "
                  f"P{f.car_ahead.position}, gap {f.gap_ahead_positions}")
        if f.car_behind:
            print(f"      behind: #{f.car_behind.car_number} ({f.car_behind.driver_short_name}) "
                  f"P{f.car_behind.position}, gap {f.gap_behind_positions}")
        # Neighbours, when present, must straddle the selected car by position.
        if f.car_ahead:
            assert f.car_ahead.position < f.selected.position, "car_ahead must be ahead"
            assert f.gap_ahead_positions >= 1
        if f.car_behind:
            assert f.car_behind.position > f.selected.position, "car_behind must be behind"
            assert f.gap_behind_positions >= 1
        if f.selected.position > 1:
            assert f.car_ahead is not None, "expected a car ahead when not leading"
        print("  ✓ focus block correct")
    except Exception as e:
        print(f"  ✗ FAILED: {type(e).__name__}: {e}")
        fails += 1

    # ------------------------------------------------------------------
    header("get_recent_events (last 60s, all types)")
    try:
        resp = get_recent_events(seconds_back=60)
        print(f"  Found {resp.count} events in last 60s")
        for ev in resp.events[:10]:
            print(f"    [{ev.event_type.value}] t={ev.race_time_s}s car={ev.car_number}")
        if not live:
            assert resp.count >= 4, f"expected ≥4 events (seed), got {resp.count}"
        else:
            zero_change = [e for e in resp.events
                           if e.event_type == EventType.OVERTAKE
                           and e.data.get("position_change") == 0]
            assert not zero_change, f"{len(zero_change)} zero-change overtakes leaked"
        print("  ✓ recent events query works")
    except Exception as e:
        print(f"  ✗ FAILED: {type(e).__name__}: {e}")
        fails += 1

    # ------------------------------------------------------------------
    header(f"get_recent_events (filtered to car {FOCUS_CAR})")
    try:
        resp = get_recent_events(seconds_back=180, car_involved=FOCUS_CAR)
        print(f"  Found {resp.count} events involving car {FOCUS_CAR}")
        assert all(e.car_number == FOCUS_CAR for e in resp.events), \
            "car filter returned other cars"
        print("  ✓ car filter works")
    except Exception as e:
        print(f"  ✗ FAILED: {type(e).__name__}: {e}")
        fails += 1

    # ------------------------------------------------------------------
    header("get_events_in_range (lap_completed)")
    try:
        if not live:
            lo, hi = 1400, 1500
        else:
            hi = race_now if race_now is not None else 300
            lo = max(0, hi - 120)
        resp = get_events_in_range(
            from_race_time_s=lo, to_race_time_s=hi,
            event_types=[EventType.LAP_COMPLETED],
        )
        print(f"  Found {resp.count} lap_completed events in {lo}-{hi}s")
        assert all(lo <= e.race_time_s <= hi for e in resp.events), \
            "range query returned out-of-window events"
        if live and hi > 80:
            assert resp.count >= 2, f"expected ≥2 lap completions, got {resp.count}"
        print("  ✓ range query works")
    except Exception as e:
        print(f"  ✗ FAILED: {type(e).__name__}: {e}")
        fails += 1

    # ------------------------------------------------------------------
    header("get_field_am_status")
    try:
        resp = get_field_am_status()
        total = len(resp.active_now) + len(resp.used_at_least_one) + len(resp.untouched)
        print(f"  active={len(resp.active_now)} used={len(resp.used_at_least_one)} "
              f"untouched={len(resp.untouched)} scenarios={resp.scenario_distribution}")
        assert total >= 20, f"expected ~21-22 cars across buckets, got {total}"
        assert resp.scenario_distribution, "expected non-empty scenario distribution"
        print("  ✓ field AM status works")
    except Exception as e:
        print(f"  ✗ FAILED: {type(e).__name__}: {e}")
        fails += 1

    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    if fails:
        print(f"  ✗ {fails} test(s) failed ({mode}, {AGENT_PACKAGE})")
        sys.exit(1)
    print(f"  ✓ All field-wide frame tools working against Firestore ({mode}, {AGENT_PACKAGE})")


if __name__ == "__main__":
    main()
