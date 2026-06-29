"""Offline verification for the commentator's #9 + #4 logic — NO GCP NEEDED.

Drives the field-wide scorer, the field-wide frame tools, and the
selection-aware loop against a SEEDED in-memory race state (a fake StateClient).
This is the CI-style proof that the re-aim and the selection narrowing behave;
the real sim-driven end-to-end is the live runbook (deploy/RUNBOOK_commentator.md).

Run:
    python scripts/verify_commentator_offline.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

# Make the repo root importable so `frontend.commentator_loop` resolves even when
# run as `python scripts/verify_commentator_offline.py` (frontend/ isn't pip-
# installed; shared/solution/starter are, via the editable install).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import shared.state_client as sc
from shared.models import (
    AttackModeState, CarState, EnergyState, Event, EventType, GPSState, RaceState,
)
from shared.scorer import score

# Force the active package to the reference for this check.
import os
os.environ.setdefault("AGENT_PACKAGE", "solution.commentator")

PASS, FAIL = "  ✓", "  ✗"
fails = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global fails
    print((PASS if cond else FAIL), label, ("" if cond else f"  <-- {detail}"))
    if not cond:
        fails += 1


# ----------------------------------------------------------------------------
# Seed: an 8-car field. car13 is the one the fan will select.
# Order: P1 c5(DEN) P2 c6(WEH) P3 c1(CAS) P4 c8(VAN) P5 c13(DAC) P6 c94(WEH2)
#        P7 c11(DIN) P8 c4(FRI)
# ----------------------------------------------------------------------------

def _car(num, drv, pos, *, am_active=False, used=0, retired=False) -> CarState:
    return CarState(
        car_number=num, driver_short_name=drv, position=pos, current_lap=10,
        speed_kmh=210.0, gps=GPSState(lat=52.0, lng=13.0, heading=90.0),
        accel_x=0.0, accel_y=0.0, brake_pct=0.0, steer=0.0, yaw_rate=0.0,
        energy=EnergyState(pct_remaining=60.0, kwh_remaining=24.0, pct_used=40.0),
        attack_mode=AttackModeState(active=am_active, activations_used=used,
                                    scenario=2, remaining_budget_s=120.0),
        is_retired=retired,
    )


def make_state(race_time_s=1000, retire_c8=False) -> RaceState:
    cars = [
        _car(5, "DEN", 1), _car(6, "WEH", 2), _car(1, "CAS", 3),
        _car(8, "VAN", 4, retired=retire_c8), _car(13, "DAC", 5),
        _car(94, "WEH2", 6), _car(11, "DIN", 7), _car(4, "FRI", 8),
    ]
    return RaceState(
        schema_version="1.0", race_id="berlin_2024_r10", race_time_s=race_time_s,
        race_duration_s=2400.0, pct_complete=42.0, race_phase="racing",
        current_leader_lap=11, cars=cars, ts_ns_wall=1,
    )


def overtake(subject, other, gained=True, t=1000) -> Event:
    return Event(
        event_type=EventType.OVERTAKE, ts_ns_wall=1, race_time_s=t,
        race_id="berlin_2024_r10", car_number=subject,
        data={"participant": str(other), "position_change": -1 if gained else 1},
    )


def am_activated(car, t=1000) -> Event:
    return Event(
        event_type=EventType.ATTACK_MODE_ACTIVATED, ts_ns_wall=1, race_time_s=t,
        race_id="berlin_2024_r10", car_number=car, data={},
    )


def race_control(category, text, cars=None, t=1000) -> Event:
    data = {"category": category, "text": text}
    if cars:
        data["attrs"] = {"cars": [{"num": c} for c in cars]}
    return Event(
        event_type=EventType.RACE_CONTROL, ts_ns_wall=1, race_time_s=t,
        race_id="berlin_2024_r10", car_number=None, data=data,
    )


# ============================================================================
# A fake StateClient — no Firestore, just returns seeded data.
# ============================================================================

class FakeStateClient:
    def __init__(self, state, events):
        self._state = state
        self._events = events

    def set(self, state=None, events=None):
        if state is not None:
            self._state = state
        if events is not None:
            self._events = events

    def get_race_state(self, *, fresh=False):
        return self._state

    def invalidate_cache(self):
        pass

    def query_events(self, *, from_race_time_s=None, to_race_time_s=None,
                     event_types=None, car_involved=None, limit=50):
        out = []
        type_vals = None
        if event_types:
            type_vals = {t.value if hasattr(t, "value") else str(t) for t in event_types}
        for e in self._events:
            if from_race_time_s is not None and e.race_time_s < from_race_time_s:
                continue
            if to_race_time_s is not None and e.race_time_s > to_race_time_s:
                continue
            if type_vals is not None and e.event_type.value not in type_vals:
                continue
            if car_involved is not None and e.car_number != car_involved:
                continue
            out.append(e)
        return out[:limit]


# ============================================================================
# 1. SCORER — field-wide ordering + selected-car boost
# ============================================================================

def test_scorer():
    print("\n== scorer: field-wide significance + selected-car boost ==")
    state = make_state()
    # Two equal mid-field overtakes: one involves car 13, one doesn't.
    ev_13 = overtake(13, 94)           # car13 passes car94 (P5 vs P6)
    ev_other = overtake(11, 4)         # car11 passes car4 (P7 vs P8)

    # No selection: both are pure overtakes, equal significance.
    cands = score(state, [ev_13, ev_other], selected_car=None)
    top_scores = sorted({c.score for c in cands})
    check("no selection -> both overtakes score equally (70)",
          all(c.score == 70 for c in cands) and len(cands) == 2,
          f"scores={[c.score for c in cands]}")

    # Select car 13: its event must outrank the equal event elsewhere.
    cands_sel = score(state, [ev_13, ev_other], selected_car=13)
    top = cands_sel[0]
    check("selected car's event ranks first", "13" in top.reason and top.score == 95,
          f"top={top.reason!r} score={top.score}")
    check("selected-car overtake is must_say (>=80)", top.must_say,
          f"must_say={top.must_say}")
    other = [c for c in cands_sel if "11" in c.reason][0]
    check("unrelated event keeps base score (70)", other.score == 70 and not other.must_say,
          f"score={other.score}")

    # Lead-battle boost: an overtake at the front outscores a mid-field one.
    ev_lead = overtake(6, 5)           # car6 passes car5 (P2 vs P1) — podium
    lead_cands = score(state, [ev_lead], selected_car=None)
    check("lead-battle overtake gets +15 (85)", lead_cands[0].score == 85,
          f"score={lead_cands[0].score}")

    # AM cluster (field-wide, unchanged).
    cluster = score(state, [], recent_am_activations=3)
    check("AM cluster fires at >=3 activations", any(c.score == 75 for c in cluster))

    # Position swing field-wide: car 11 jumps P7 -> P4 (gained 3).
    swing_state = make_state()
    for c in swing_state.cars:
        if c.car_number == 11:
            c.position = 4
        elif c.car_number in (8, 13, 94):
            c.position += 1  # shoved back by the climber
    prev = {5: 1, 6: 2, 1: 3, 8: 4, 13: 5, 94: 6, 11: 7, 4: 8}
    swing = score(swing_state, [], prev_positions=prev)
    c11 = [c for c in swing if "car 11" in c.reason]
    check("field-wide swing detected for a non-selected car", bool(c11),
          f"candidates={[c.reason for c in swing]}")
    # 3-place gain = base 55 + 5*(3-1) = 65; P4 is outside the podium cutoff so
    # no lead-battle boost.
    check("3-place swing scores base + 5*(n-1) = 65",
          bool(c11) and c11[0].score == 65, f"score={c11[0].score if c11 else None}")

    # Race control: safety car is must_say regardless of selection.
    sc_rc = score(state, [race_control("safety_car.deployed", "Safety car")],
                  selected_car=None)
    check("safety car is must_say", sc_rc[0].must_say and sc_rc[0].score == 95)

    # Race control naming the selected car gets boosted.
    pen = score(state, [race_control("penalty.5s", "5s penalty", cars=[13])],
                selected_car=13)
    check("penalty naming selected car is boosted (60+25=85)", pen[0].score == 85,
          f"score={pen[0].score}")


# ============================================================================
# 2. FRAME TOOLS — field-wide shape + focus block
# ============================================================================

def test_frame_tools():
    print("\n== frame tools: field-wide get_field_state + focus block ==")
    fake = FakeStateClient(make_state(), [])
    sc._singleton = fake  # inject — no Firestore touched

    from solution.commentator.tools.frame_tools import get_field_state

    resp = get_field_state()
    check("returns every running car (8)", len(resp.cars) == 8, f"n={len(resp.cars)}")
    check("cars are position-sorted",
          [c.position for c in resp.cars] == list(range(1, 9)),
          f"positions={[c.position for c in resp.cars]}")
    check("no focus block when no car selected", resp.focus is None)
    check("carries race_wall_time_ns", resp.race_wall_time_ns > 0)
    check("carries current_leader_lap", resp.current_leader_lap == 11)

    resp_sel = get_field_state(selected_car=13)
    f = resp_sel.focus
    check("focus block present when car selected", f is not None)
    check("focus.selected is car 13", f and f.selected.car_number == 13)
    check("focus.car_ahead is car 8 (P4)", f and f.car_ahead and f.car_ahead.car_number == 8,
          f"ahead={f.car_ahead.car_number if f and f.car_ahead else None}")
    check("focus.car_behind is car 94 (P6)", f and f.car_behind and f.car_behind.car_number == 94)
    check("position gaps are 1 / 1",
          f and f.gap_ahead_positions == 1 and f.gap_behind_positions == 1)

    # Retire the car directly ahead — nearest running ahead becomes car 1 (P3),
    # so the position gap widens to 2.
    fake.set(state=make_state(retire_c8=True))
    resp_ret = get_field_state(selected_car=13)
    f2 = resp_ret.focus
    check("retired neighbour skipped: nearest ahead is car 1", f2 and f2.car_ahead.car_number == 1,
          f"ahead={f2.car_ahead.car_number if f2 and f2.car_ahead else None}")
    check("gap widens to 2 positions after a retirement", f2 and f2.gap_ahead_positions == 2,
          f"gap={f2.gap_ahead_positions if f2 else None}")
    check("retired car dropped from the field list",
          all(c.car_number != 8 for c in resp_ret.cars))

    # Selecting a car that isn't running -> no focus, no crash.
    resp_none = get_field_state(selected_car=999)
    check("unknown selected car -> focus is None (no crash)", resp_none.focus is None)


# ============================================================================
# 3. LOOP — selection-aware firing (run the real loop briefly with fakes)
# ============================================================================

class FakeAgent:
    def __init__(self):
        self.prompts = []

    async def fire(self, prompt):
        self.prompts.append(prompt)
        return ("Car 13 dives down the inside of car 94 for fifth.", 0, 0.1)

    async def ask(self, q):
        return "ok"

    def reset_qa_session(self):
        pass

    async def close(self):
        pass


async def _drive_loop(selected_car):
    from frontend.commentator_loop import CommentatorLoop

    fake_state = FakeStateClient(make_state(race_time_s=1000),
                                 [overtake(13, 94, t=1000)])
    agent = FakeAgent()
    broadcasts = []

    async def broadcast(msg):
        broadcasts.append(msg)

    loop = CommentatorLoop(
        broadcast, debounce_s=0.0, must_say_gap_s=0.0, poll_s=0.01,
        agent_client=agent, state_client=fake_state,
    )
    if selected_car is not None:
        loop.set_selection(selected_car)

    task = asyncio.create_task(loop.run())
    # let a few polls happen
    for _ in range(50):
        await asyncio.sleep(0.01)
        if broadcasts:
            break
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    return agent, broadcasts


def test_loop():
    print("\n== loop: selection-aware firing ==")

    # With a selection, the watching line + focus must reach the prompt.
    agent, broadcasts = asyncio.run(_drive_loop(selected_car=13))
    check("loop fired at least one call (selected)", bool(broadcasts),
          "no broadcast")
    if broadcasts:
        check("broadcast records the selected car", broadcasts[0].get("selected_car") == 13)
    if agent.prompts:
        p = agent.prompts[0]
        check("prompt injects 'fan is watching car 13'", "watching car 13" in p.lower(),
              "watching line missing")
        check("prompt's snapshot carries a focus block", '"focus"' in p and '"selected"' in p)
        # the focus snapshot should name the neighbours
        check("focus snapshot includes the car-ahead (8)", '"car": 8' in p or '"car":8' in p)

    # Without a selection, it still fires but with no watching line / null selection.
    agent2, broadcasts2 = asyncio.run(_drive_loop(selected_car=None))
    check("loop fired at least one call (no selection)", bool(broadcasts2))
    if broadcasts2:
        check("broadcast selected_car is null when none selected",
              broadcasts2[0].get("selected_car") is None)
    if agent2.prompts:
        check("no watching line when nothing selected",
              "watching car" not in agent2.prompts[0].lower())


def main():
    test_scorer()
    test_frame_tools()
    test_loop()
    print("\n" + "=" * 60)
    if fails:
        print(f"  ✗ {fails} check(s) failed")
        sys.exit(1)
    print("  ✓ all offline checks passed")


if __name__ == "__main__":
    main()
