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

- `agent.py` — ADK `root_agent` wiring (model, retry, field-wide frame tools, TTS hook).
- `config.py` — race scope, AM constants, the `race_time → 2024 wall clock` bridge.
- `prompts.py` — broadcast persona + selection-aware instruction.
- `tools/frame_tools.py` — field-wide live-state tools (see spec).
