# Commentator — STARTER

Build the live **broadcast commentator** for the Berlin R10 replay: a third-person
voice that narrates the whole field ("out of turn 2, car 5 is through on car 6")
and **narrows focus to the car the fan selects**, spoken aloud via TTS.

## You build TWO files

Everything else is given working infrastructure — you should not need to read it
in depth.

| File | What you do |
|---|---|
| `prompts.py` | **The main lesson.** Author the broadcast persona: third-person, field-wide, selection-aware, TTS-friendly, honest. The trigger-prompt builders at the bottom are given. |
| `agent.py` | One short wiring step: construct `root_agent` from your persona + the four given tools. |

## Given (don't edit)

- `tools/frame_tools.py` — field-wide live tools over Firestore "now":
  `get_field_state(selected_car)` (whole field + a focus block on the selected
  car), `get_recent_events`, `get_events_in_range`, `get_field_am_status`.
- `config.py` — race scope, Attack Mode constants, the race→2024 time bridge.
- `snapshot.py` — the authoritative "moment" pinned into each trigger prompt.
- `shared/scorer.py` — the deterministic significance scorer (field-wide, with a
  boost toward the selected car). Decides *when* to speak; your agent decides
  *what*.
- `frontend/commentator_loop.py` — the poll→score→fire→broadcast loop; holds the
  fan's selection and threads it through.

## Tier ladder (v2)

- **A — stand up the commentator.** Write the persona in `prompts.py` and wire
  `root_agent` in `agent.py`. Try it with no persona first and watch it invent —
  then ground it. (Ungrounded = a podcast.)
- **B — call the real race.** The field-wide tools are already wired; confirm the
  agent narrates actual sim events (validate with `scripts/test_frame_tools.py`).
- **C — selection-aware.** Make your persona open on the fan's selected car and
  its battle when the snapshot says one is selected. **The distinctive beat.**
- **D — out loud.** It's read by TTS — keep the voice spoken, numbers as digits,
  no markdown.

## Run it

```bash
source activate.sh                 # AGENT_PACKAGE defaults to starter.commentator
python scripts/test_frame_tools.py --live      # prove the field-wide tools
python scripts/local_commentator.py --duration 380 --verbose   # watch it commentate
```

Selection: send a car number to the loop (the UI does this over the websocket);
in the harness use `--select <car>` to simulate the fan clicking a car and watch
the commentary narrow.

Reference solution: `solution/commentator/`. Spec: `spec/frame_tools_scorer_reaim.md`.
