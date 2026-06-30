# Commentator agent (ADK) — reference solution

A live **continuous play-by-play broadcaster** over the Berlin R10 replay. A flowing
stream of third-person commentary (2-3 sentences per beat, paced to reading time),
not sparse bulletins. Two modes, one agent:

- **Field-wide** (default): a running story led by the front of the race — "Cassidy
  still leads from Wehrlein, but Dennis is climbing — up to P3."
- **Selection-aware**: when the fan selects a car in the UI, that car becomes the main
  story every line (its battle, what just changed for it), with a glance at the front.

This is the descendant of Ch2's race engineer, **re-aimed twice**: from a first-person
"our car #13" engineer to a third-person field broadcaster, and then from an event
**gate** (speak only when significant) to a continuous **director** model — the scorer
ranks what's happening, the model narrates it in a flowing stream that builds on its
last lines. The new learning is the field POV, the broadcast persona, the selection-aware
focus, and that gate→director flip. See `spec/frame_tools_scorer_reaim.md` §5.

## What's reused vs new

| Piece | Origin | Change |
|---|---|---|
| ADK agent chassis (`agent.py`) | Ch2 `solution/race_engineer/agent.py` | drop the Toolbox dependency (commentator doesn't need BQ); keep retry/model config |
| `config.py` (time bridge, AM constants) | Ch2 | drop `OUR_CAR_*`; add nothing car-specific — commentary is field-wide |
| `tools/frame_tools.py` | Ch2 (car-13 POV) | **RE-AIM → field-wide + `selected_car` param.** See `spec/frame_tools_scorer_reaim.md` |
| `shared/scorer.py` | Ch2 (us-centric weights) | **RE-AIM → field-wide events + selected-car boost.** Same spec |
| TTS | Ch2 `frontend/tts.py` | as-is; optional toggle (default muted — built for on-screen reading) |
| The loop | Ch2 `frontend/engineer_loop.py` (gate) | becomes `commentator_loop.py` — a **continuous director**: rank → narrate every beat, paced by `reading_gap_s`, with rolling recent-line memory. No threshold/debounce |
| Prompts | Ch2 event/recap builders | one `build_commentary_prompt(recent_lines, action, snapshot, watching)` |

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
- `prompts.py` — continuous-broadcast persona + `build_commentary_prompt`
  (recent lines + ranked action + live field + the `watching` selection line).
- `snapshot.py` — field-wide snapshot (leading order + focus block) for each beat.
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
