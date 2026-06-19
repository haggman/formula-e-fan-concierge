"""Validate the agent's frame tools against Firestore.

THE FRAME-TOOLS VALIDATOR (Tier D: prove the GIVEN tools against the live
replay). Resolved through the AGENT_PACKAGE seam (shared/agent_pkg.py), so
with activate.sh defaults this tests starter/race_engineer/tools/
frame_tools.py — which ships COMPLETE: every section should print ✓ as-is,
and a ✗ means environment (simulator not running, stale Firestore), not
code. If you took the BONUS "build your own frame tool" ticket, this is
your checklist. To validate the reference instead:
    AGENT_PACKAGE=solution.race_engineer python scripts/test_frame_tools.py

Two modes:

SEED MODE (default) — run against the canonical static sample frame:
    python scripts/seed_test_state.py
    python scripts/test_frame_tools.py
  Asserts exact values from the seeded frame (DAC P2, safety car, MOR in AM).

LIVE MODE — run against a live simulator replay:
    python scripts/test_frame_tools.py --live
  Same six tool exercises, but seed-specific asserts are replaced with
  live-appropriate checks: structural sanity, query mechanics, and
  data-quality invariants (e.g. lap_completed events must carry real
  nonzero top speeds — validates the frames pipeline end to end).
"""
from __future__ import annotations

from shared.script_env import require_venv
require_venv()

import argparse
import sys

from shared.agent_pkg import AGENT_PACKAGE, agent_module
from shared.models import EventType

# Resolve the frame tools from the ACTIVE agent package — the same import
# path ADK uses when the agent calls them.
_ft = agent_module("tools.frame_tools")
get_current_state = _ft.get_current_state
get_recent_events = _ft.get_recent_events
get_events_in_range = _ft.get_events_in_range
get_field_am_status = _ft.get_field_am_status


def header(label: str) -> None:
    print(f"\n── {label} ──")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true",
        help="validate against a live replay instead of the static seed frame",
    )
    args = parser.parse_args()
    live = args.live
    mode = "LIVE replay" if live else "SEED frame"
    print(f"Mode: {mode}  |  Package: {AGENT_PACKAGE}")

    fails = 0
    race_now = None  # set by the first tool call, reused for live windows

    # ------------------------------------------------------------------
    header("get_current_state")
    try:
        resp = get_current_state()
        race_now = resp.race_time_s
        print(f"  Our car {resp.our_car_number} ({resp.our_driver}) — P{resp.position} on lap {resp.current_lap}")
        print(f"  Speed: {resp.speed_kmh} km/h, Energy: {resp.energy_pct_remaining}% remaining")
        print(f"  AM scenario {resp.am_scenario} ({resp.am_scenario_name}), "
              f"active={resp.am_active}, used={resp.am_activations_used}, "
              f"budget={resp.am_remaining_budget_s}s")
        print(f"  Ahead: {resp.car_ahead}")
        print(f"  Behind: {resp.car_behind}")
        print(f"  Race: {resp.race_phase} at t={resp.race_time_s}s, leader on lap {resp.current_leader_lap}")

        # Mode-independent sanity
        assert resp.our_car_number == 13, "expected car 13"
        assert resp.our_driver == "DAC", "expected DAC"
        assert 1 <= resp.position <= 22, f"position {resp.position} out of range"
        assert 0 <= resp.energy_pct_remaining <= 100, "energy pct out of range"

        if not live:
            # Seed-frame exact values
            assert resp.position == 2, "expected P2 (sample frame)"
            assert resp.car_ahead and resp.car_ahead.driver_short_name == "CAS", "expected Cassidy ahead"
            assert resp.car_behind and resp.car_behind.driver_short_name == "ROW", "expected Rowland behind"
            assert resp.race_phase == "safety_car", "expected safety_car phase"
        else:
            # Live: neighbors must exist unless at field edges
            if resp.position > 1:
                assert resp.car_ahead is not None, "expected a car ahead when not P1"
            if resp.position < 22:
                assert resp.car_behind is not None, "expected a car behind when not last"
        print("  ✓ all sanity checks pass")
    except Exception as e:
        print(f"  ✗ FAILED: {type(e).__name__}: {e}")
        fails += 1

    # ------------------------------------------------------------------
    header("get_recent_events (last 60s, all types)")
    try:
        resp = get_recent_events(seconds_back=60)
        print(f"  Found {resp.count} events in last 60s")
        for ev in resp.events[:15]:
            print(f"    [{ev.event_type.value}] t={ev.race_time_s}s car={ev.car_number} data={ev.data}")
        if resp.count > 15:
            print(f"    ... +{resp.count - 15} more")

        if not live:
            assert resp.count >= 4, f"expected ≥4 events (seeded), got {resp.count}"
        else:
            # Live data-quality invariants
            zero_change = [e for e in resp.events
                           if e.event_type == EventType.OVERTAKE
                           and e.data.get("position_change") == 0]
            assert not zero_change, \
                f"{len(zero_change)} zero-change overtakes — frames_v2+ filter not in effect?"
            laps = [e for e in resp.events if e.event_type == EventType.LAP_COMPLETED]
            bad_ts = [e for e in laps if not e.data.get("top_speed_kmh")]
            assert not bad_ts, \
                f"{len(bad_ts)} lap_completed events with zero/None top speed — frames_v2+ not flowing?"
            if laps:
                print(f"  ○ {len(laps)} lap_completed events, all with real top speeds "
                      f"(e.g. {laps[0].data.get('top_speed_kmh')} km/h)")
        print("  ✓ all sanity checks pass")
    except Exception as e:
        print(f"  ✗ FAILED: {type(e).__name__}: {e}")
        fails += 1

    # ------------------------------------------------------------------
    header("get_recent_events (only race_control)")
    try:
        resp = get_recent_events(
            seconds_back=120,
            event_types=[EventType.RACE_CONTROL],
        )
        print(f"  Found {resp.count} race_control events")
        for ev in resp.events:
            print(f"    {ev.data}")
        if not live:
            assert resp.count >= 1, "expected at least 1 race_control event (seeded)"
        else:
            # RC messages are sparse early in the race — zero is a valid result.
            # The check here is that the type filter executed without error and
            # returned ONLY race_control events.
            assert all(e.event_type == EventType.RACE_CONTROL for e in resp.events), \
                "type filter returned non-race_control events"
            if resp.count == 0:
                print("  ○ none in window (normal early-race) — filter mechanics still verified")
        print("  ✓ filter works")
    except Exception as e:
        print(f"  ✗ FAILED: {type(e).__name__}: {e}")
        fails += 1

    # ------------------------------------------------------------------
    header("get_recent_events (filtered to a single car)")
    try:
        # Seed mode: car 48 (MOR) has a seeded AM activation.
        # Live mode: use our own car — DAC generates events steadily.
        target_car = 48 if not live else 13
        resp = get_recent_events(seconds_back=120, car_involved=target_car)
        print(f"  Found {resp.count} events involving car {target_car}")
        for ev in resp.events[:10]:
            print(f"    [{ev.event_type.value}] data={ev.data}")
        assert all(e.car_number == target_car for e in resp.events), \
            "car filter returned events for other cars"
        if not live:
            assert resp.count >= 1, "expected at least 1 event involving car 48 (AM activation)"
        print("  ✓ car filter works")
    except Exception as e:
        print(f"  ✗ FAILED: {type(e).__name__}: {e}")
        fails += 1

    # ------------------------------------------------------------------
    header("get_events_in_range")
    try:
        if not live:
            lo, hi = 1400, 1500  # brackets the seeded frame at t=1449
        else:
            hi = race_now if race_now is not None else 300
            lo = max(0, hi - 120)
        resp = get_events_in_range(
            from_race_time_s=lo,
            to_race_time_s=hi,
            event_types=[EventType.LAP_COMPLETED],
        )
        print(f"  Found {resp.count} lap_completed events in range {lo}-{hi}s")
        for ev in resp.events[:10]:
            print(f"    car {ev.car_number}: {ev.data}")
        if not live:
            assert resp.count >= 2, f"expected ≥2 lap completions, got {resp.count}"
        else:
            # 120s ≈ 2 laps — the whole running field should have completed laps,
            # unless we're in the first lap of the race.
            if hi > 80:
                assert resp.count >= 2, \
                    f"expected ≥2 lap completions in a {hi-lo}s window at t={hi}"
            assert all(lo <= e.race_time_s <= hi for e in resp.events), \
                "range query returned events outside the window"
        print("  ✓ range query works")
    except Exception as e:
        print(f"  ✗ FAILED: {type(e).__name__}: {e}")
        fails += 1

    # ------------------------------------------------------------------
    header("get_field_am_status")
    try:
        resp = get_field_am_status()
        print(f"  Active now: {len(resp.active_now)} car(s)")
        for s in resp.active_now:
            print(f"    P{s.position} #{s.car_number} ({s.driver_short_name}) "
                  f"scenario {s.scenario}, budget {s.remaining_budget_s}s")
        print(f"  Used at least one: {len(resp.used_at_least_one)} cars")
        print(f"  Untouched: {len(resp.untouched)} cars")
        print(f"  Scenario distribution: {resp.scenario_distribution}")

        total = len(resp.active_now) + len(resp.used_at_least_one) + len(resp.untouched)
        assert total >= 20, f"expected ~21-22 running cars across buckets, got {total}"
        assert resp.scenario_distribution, "expected non-empty scenario distribution"
        if not live:
            assert any(s.car_number == 48 for s in resp.active_now), \
                "expected car 48 (MOR) in active_now (seeded)"
        print("  ✓ all sanity checks pass")
    except Exception as e:
        print(f"  ✗ FAILED: {type(e).__name__}: {e}")
        fails += 1

    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    if fails:
        print(f"  ✗ {fails} test(s) failed ({mode}, {AGENT_PACKAGE})")
        sys.exit(1)
    else:
        print(f"  ✓ All frame tools working against Firestore ({mode}, {AGENT_PACKAGE})")


if __name__ == "__main__":
    main()
