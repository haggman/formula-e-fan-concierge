# Commentator — verify & run runbook

End-to-end proof of the live **broadcast commentator** (work items #9 + #4): the
field-wide frame tools + re-aimed scorer, and the ADK broadcaster that narrates
the whole field and **narrows onto a selected car**. Two layers of verification:

1. **Offline (no GCP)** — runs anywhere, proves the re-aim and the selection
   logic in seconds.
2. **Live (your GCP project)** — the real sim-driven end-to-end: the commentator
   calling actual replay events, and following a selected car.

Run live steps in **Cloud Shell** from the repo root with the target project
selected. The data layer here is the same one you stood up for the subagent
(`source activate.sh` → `bash setup/all.sh`) — if it's already up, skip to §2.

## 0. Offline check (do this first — no GCP needed)

```bash
source activate.sh
python scripts/verify_commentator_offline.py
```

Proves, against a seeded in-memory field: the scorer ranks field-wide
significance and boosts the selected car (a selected-car overtake outranks an
equal event elsewhere and becomes must-say); `get_field_state` returns the whole
field position-sorted and a correct `focus` block (nearest running car
ahead/behind, position gaps that widen across a retirement); and the loop fires
selection-aware (the "fan is watching car N" line + focus snapshot reach the
prompt). All ✓ = the logic is sound; the rest is environment.

## 1. Stand up the data plane (the commentator reads Firestore "now")

```bash
gcloud config set project YOUR_PROJECT_ID
export REGION=us-central1
source activate.sh
bash setup/all.sh        # 1 APIs · 2 BigQuery · 3 toolbox · 4 Firestore ·
                         # 5 state writer · 6 simulator · verify
```

The commentator only needs Firestore "now" (it does NOT query BigQuery), so once
the simulator is publishing and the state writer is filling `race_states` /
`race_events`, you're ready.

### 1.5 Start the simulator in commentator mode (curl)

The sim is the private Cloud Run service `fe-simulator`. Control it over HTTP. If
it's paused mid-race (e.g. left over from subagent testing), restart it from the
green flag and run at 2x — that's the right cadence for trigger work (380 s ≈ laps
1–11).

```bash
export SIM_URL="$(gcloud run services describe fe-simulator --region "$REGION" --format='value(status.url)')"
AUTH=(-H "Authorization: Bearer $(gcloud auth print-identity-token)")   # fe-simulator is private

# Fresh replay from the start, at 2x, running:
curl -s "${AUTH[@]}" -X POST "$SIM_URL/restart"
curl -s "${AUTH[@]}" -X POST "$SIM_URL/speed"  -H 'Content-Type: application/json' -d '{"multiplier": 2.0}'
curl -s "${AUTH[@]}" -X POST "$SIM_URL/resume"
curl -s "${AUTH[@]}" "$SIM_URL/status"          # confirm race_time_s advancing, paused:false
```

Other controls: `POST /pause` (freeze), `POST /jump {"race_time_s": N}` (seek to a
moment), `POST /speed {"multiplier": 1.0}` (real time). Re-run `GET /status` any
time to see where the replay is. Leave it running while you do the steps below.

## 2. Prove the field-wide frame tools against the live replay

```bash
# reference tools:
AGENT_PACKAGE=solution.commentator python scripts/test_frame_tools.py --live
# the student build (activate.sh default = starter.commentator):
python scripts/test_frame_tools.py --live
```

Expect ✓ on: whole field returned & position-sorted; the `focus` block for car
13 (selected car + nearest ahead/behind + gaps); recent/range event queries; the
per-car filter; field AM status. A ✗ here means the replay isn't live or
Firestore is stale, not a code bug.

## 3. Watch it commentate (the live end-to-end)

```bash
# field-wide — narrates the most significant action across the whole field:
python scripts/local_commentator.py --duration 380 --verbose

# selection-aware — simulate the fan clicking car 13; commentary opens on it:
python scripts/local_commentator.py --select 13 --duration 380 --verbose
```

What good looks like:
- **Field-wide:** third-person calls on the leaders and the biggest movers
  ("car 5 is through on car 6 into turn 1"), recaps on lap boundaries, must-say on
  safety car / chequered. No first-person, no invented gaps in seconds.
- **`--select 13`:** the same race, but calls now open on car 13 and its battle
  ("car 13 holds off car 94 for fifth"), and events near car 13 fire more readily
  (the selected-car boost). It never goes fully blind to the front of the race.

Switch `--select` between runs to feel the narrowing. In the product the UI sends
this over the websocket (`{type:"select", car_number}`) and the loop's
`set_selection()` swaps it live mid-race.

## 4. In the frontend service (when #7 wires the UI)

The loop is `frontend/commentator_loop.py` (`CommentatorLoop`). It's a drop-in for
Ch2's `EngineerLoop` with two wiring points for the frontend team (#7):
- on a `{type:"select", car_number}` websocket message → `loop.set_selection(n)`
  (or `set_selection(None)` to clear);
- deliveries broadcast as `{type:"radio", kind, text, selected_car, ...}` — the
  same envelope Ch2 used, plus `selected_car`.

`frontend/main.py` still imports Ch2's `EngineerLoop` / `OUR_CAR_NUMBER` /
`tools.state_client` — that swap (to `CommentatorLoop`, drop `OUR_CAR_NUMBER`, read
`shared.state_client`) and the `setup/8` deploy rename are #7/#8 work, intentionally
not done here. The commentator package, loop, scorer, tools, and harness are
complete and proven; the frontend rewire consumes them.

## Notes

- **Time-honesty is not a commentator concern.** It narrates the live moment only;
  it never queries BigQuery and has no future-leak surface (that discipline lives
  in the race-data subagent).
- **AGENT_PACKAGE seam** picks the build: `starter.commentator` (default) or
  `solution.commentator`. Same loop, same tools, the student's persona drives it.
- **Model:** `FE_MODEL` (default `gemini-3.5-flash`); under sustained 429s, a GA
  model on a regional endpoint is the escape (`export FE_MODEL=gemini-2.5-flash
  GOOGLE_CLOUD_LOCATION=us-central1`).
