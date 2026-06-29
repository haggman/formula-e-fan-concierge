# Commentator agent (ADK) — reference solution

A live **broadcaster** over the Berlin R10 replay. Two modes, one agent:

- **Field-wide** (default): a running story of the whole field in third person —
  "out of Turn 2, car 5 is through on car 6."
- **Selection-aware**: when the fan selects a car in the UI, commentary **narrows focus**
  to that car and its battle with whoever's next to it.

This is the direct descendant of Ch2's race engineer, **re-aimed** from a first-person
"our car #13" engineer to a third-person field broadcaster. Treat the reuse as a feature;
the new learning is the field POV, the broadcast persona, and the selection-aware focus.

## What's reused vs new

| Piece | Origin | Change |
|---|---|---|
| ADK agent chassis (`agent.py`) | Ch2 `solution/race_engineer/agent.py` | drop the Toolbox dependency (commentator doesn't need BQ); keep retry/model config |
| `config.py` (time bridge, AM constants) | Ch2 | drop `OUR_CAR_*`; add nothing car-specific — commentary is field-wide |
| `tools/frame_tools.py` | Ch2 (car-13 POV) | **RE-AIM → field-wide + `selected_car` param.** See `spec/frame_tools_scorer_reaim.md` |
| `shared/scorer.py` | Ch2 (us-centric weights) | **RE-AIM → field-wide events + selected-car boost.** Same spec |
| TTS | Ch2 `frontend/tts.py` | as-is |
| The poll→score→fire→broadcast loop | Ch2 `frontend/engineer_loop.py` | becomes `commentator_loop.py`; resolves the active package via the `AGENT_PACKAGE` seam |

## Selected-car signal path (open #3)

The UI selection reaches the commentator loop as a websocket message
(`{type: "select", car_number: <int|null>}`). The loop holds the current selection and:
1. passes `selected_car` to the field-wide frame tools and the scorer (boost), and
2. injects "the fan is watching car N" into the commentator's per-fire snapshot/prompt.
`null` = no selection → pure field-wide. Same websocket carries `{type: "radio"}` deliveries
back out. See `spec/frame_tools_scorer_reaim.md` for the boost mechanics.

## Tier mapping (v2 ladder)

- **A** — stand up the ADK agent, broadcast prompt (ungrounded → invents stats).
- **B** — wire the field-wide frame tools (Firestore "now").
- **C** — selection-aware: commentary re-aims on the clicked car.
- **D** — broadcast persona, out loud (TTS).

## Files

- `agent.py` — ADK `root_agent` wiring (model, retry, the four field-wide frame
  tools; no Toolbox — the commentator narrates "now", it doesn't query BigQuery).
- `config.py` — race scope, AM constants, the `race_time → 2024 wall clock` bridge
  (no car identity — the commentator is field-wide).
- `prompts.py` — broadcast persona + selection-aware instruction + the proactive
  trigger-prompt builders (with the `watching` injection).
- `snapshot.py` — field-wide authoritative snapshot (leading order + focus block).
- `tools/frame_tools.py` — field-wide live-state tools (`get_field_state(selected_car)`
  + focus block; `get_recent_events` / `get_events_in_range` / `get_field_am_status`
  ported from Ch2). See `spec/frame_tools_scorer_reaim.md`.

The loop, scorer, and state reader live outside the package: the selection-aware
`frontend/commentator_loop.py`, the field-wide `shared/scorer.py`, and the
vendored `shared/state_client.py`.

## Status & verification (built 2026-06-29)

Built and verified. The scorer re-aim, the field-wide tools + focus block, and
the selection-aware loop are proven offline (no GCP) by
`scripts/verify_commentator_offline.py` — all checks pass. The live, sim-driven
end-to-end (the commentator calling real replay events and following a selected
car) is in `deploy/RUNBOOK_commentator.md`:

```bash
python scripts/verify_commentator_offline.py        # no GCP — logic proof
python scripts/test_frame_tools.py --live           # field-wide tools vs live Firestore
python scripts/local_commentator.py --select 13 --verbose   # watch it narrow onto car 13
```

The `{type:"select"}` websocket handler in `frontend/main.py` and the `setup/8`
deploy rename are the frontend/deploy rewire (#7/#8) — the package, loop, scorer,
and tools are complete and ready for them to consume.
