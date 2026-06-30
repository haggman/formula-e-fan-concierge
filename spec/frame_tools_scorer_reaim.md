# Re-aim: frame_tools + scorer — "our car #13" → field-wide with selected-car boost

Resolves the re-aim half of the build. Both pieces are written from car #13's first-person
"our car" POV (Ch2's race engineer). The commentator is a third-person field broadcaster, so
both move to a **field-wide** view with a **boost toward the fan's selected car**.

Selected-car signal path (open **#3**): the UI sends `{type:"select", car_number:<int|null>}`
over the websocket; the commentator loop holds the current selection and threads it into the
frame tools (`selected_car`) and the scorer (`selected_car` boost). `null` = pure field-wide.

---

## 1. `frame_tools.py` (commentator/tools + subagent now_tools)

Ch2 surface (car-13 POV) → new surface:

| Ch2 (car-13) | New | Change |
|---|---|---|
| `get_current_state()` → one car (#13) + neighbors | `get_field_state(selected_car=None)` | Return **all running cars** (position-sorted: number, driver, position, speed, energy, AM). If `selected_car` set, add a `focus` block: that car + nearest ahead/behind + gaps. |
| `get_recent_events(...)` | same | **Kept** — already field-wide (filters by car only on request). |
| `get_events_in_range(...)` | same | **Kept.** |
| `get_field_am_status()` | same | **Kept** — already field-wide (3 buckets across the field). |

Notes:
- `CurrentStateResponse` (single-car) is replaced by `FieldStateResponse { cars: list[CarLine],
  focus: FocusBlock | None, race_phase, race_time_s, race_wall_time_ns, current_leader_lap }`.
- `OUR_CAR_NUMBER` and `_require_our_car()` are **deleted**. No car is special at the data
  layer; "special" is a runtime `selected_car` argument.
- Keep `race_wall_time_ns` on responses (consistency; the subagent's now_tools need it to bound
  BigQuery — see the CX spike spec).
- The subagent's `now_tools` are the same field-wide reads plus `get_car_now(car_number)` (any
  car), sharing `shared/state_client.py`.

## 2. `shared/scorer.py` — field-wide events + selected-car boost

Ch2 weights are us-centric: `SCORE_WE_GOT_PASSED`, `SCORE_WE_PASSED`, `SCORE_OUR_AM_*`,
`RC_INVOLVES_US`, plus `our_car` / `prev_our_position` params and `_rc_names_us` / `_is_neighbor`
helpers anchored on "us." Re-aim:

**Signature**
```python
def score(state, new_events, *, selected_car: int | None = None,
          recent_am_activations=0, prev_positions: dict[int,int] | None = None
          ) -> list[TriggerCandidate]:
```
- `our_car: int = 13` → `selected_car: int | None = None`.
- `prev_our_position: int` → `prev_positions: dict[car -> position]` (track swings field-wide,
  not just one car).

**Weights → field-relevance.** Replace "us"-centric constants with event-significance
constants that apply to *any* car, then **add a boost** when the event involves `selected_car`:
```
SCORE_OVERTAKE            = 70   # any pass; lead-change / podium positions score higher
SCORE_AM_ACTIVATED        = 60   # any car takes Attack Mode
SCORE_AM_CLUSTER          = 75   # unchanged (already field-wide)
SCORE_POSITION_SWING_BASE = 55   # any car gaining/losing >=2 net places
SELECTED_CAR_BOOST        = 25   # added when the event involves the selected car
LEAD_BATTLE_BOOST         = 15   # events at/near P1–P3
RC_SEVERITY               = ...  # KEEP the existing race-control severity table as-is
```
- Drop `SCORE_WE_*` / `SCORE_OUR_AM_*` / `RC_INVOLVES_US`; fold "names a car we care about"
  into the selected-car boost.
- `must_say` keys off field-critical race control (safety car / red / chequered) — unchanged —
  **plus** anything involving the selected car above a threshold (so the broadcast never
  ignores what the fan is watching).
- Helpers: `_is_neighbor(state, car_a, car_b)` becomes symmetric (any two cars); `_rc_names_us`
  → `_rc_names_car(e, car)` reused with `selected_car`.

**Behavioural effect:** with no selection, the commentator narrates the most significant field
action (lead battles, big swings, AM clusters, race control). With a selection, the same events
near *that* car bubble to the top, so commentary "follows what you're watching" without going
blind to the rest of the field.

## 3. Loop changes (`commentator_loop.py`, was `engineer_loop.py`)

- Hold `selected_car` from the websocket; pass to `get_field_state` and `score`.
- Track `prev_positions` as a dict across polls (for field-wide swing detection).
- Inject "the fan is watching car N (driver)" into the per-fire snapshot/prompt when set.
- Keep all Ch2 trigger *policy* (per-type debounce, must-say hold with fresh snapshot,
  overdue-summary guarantee, tool/time budget, drop-don't-crash). Resolve the active package
  via the existing `AGENT_PACKAGE` seam (starter vs solution commentator).

## 4. Tests to port/retarget

- `scripts/test_frame_tools.py` → assert field-wide shape + the `focus` block for a selection.
- Scorer unit tests → drop "our car" fixtures; add "event near selected car outranks equal
  event elsewhere" and "no selection → pure significance ordering."

---

## 5. BUILT — resolutions & learnings (2026-06-29)

#9 and #4 (the commentator) are implemented and verified. What landed, and the
decisions made while building:

**Scorer (`shared/scorer.py`).** Re-aimed exactly to §2: dropped the `SCORE_WE_*` /
`SCORE_OUR_AM_*` / `RC_INVOLVES_US` constants and the `our_car` / `prev_our_position`
params. New signature is `score(state, new_events, *, selected_car=None,
recent_am_activations=0, prev_positions=None)`. Constants as spec'd
(`SCORE_OVERTAKE=70`, `SCORE_AM_ACTIVATED=60`, `SCORE_AM_CLUSTER=75`,
`SCORE_POSITION_SWING_BASE=55`, `SELECTED_CAR_BOOST=25`, `LEAD_BATTLE_BOOST=15`),
RC severity table kept verbatim. Added while building (small, documented):
`PODIUM_MAX=3` (the "near the lead" cutoff for `LEAD_BATTLE_BOOST`),
`RC_MUST_SAY_MIN=88` (safety car / red / chequered — the field-critical must-say
floor, unchanged from Ch2's 88), and `SELECTED_CAR_MUST_SAY_MIN=80` (a boosted
selected-car event at/above this becomes must-say, so the broadcast never skips
what the fan is watching). `_is_neighbor` is now symmetric (any two cars);
`_rc_names_us` → `_rc_names_car(e, car)`. Two judgement calls: an Attack-Mode
activation "involves the selected car" if it's the selected car **or a car
directly next to it** (a rival arming 50 kW is news for the fan's battle); AM
**deactivation** is a quiet beat field-wide, so it's only emitted for the selected
car. Position swings now scan every running car off `prev_positions`.

**Frame tools (`*/commentator/tools/frame_tools.py`).** `get_field_state(selected_car=None)`
returns `FieldStateResponse { cars: list[CarLine], focus: FocusBlock|None,
selected_car, race_phase, race_time_s, current_leader_lap, race_wall_time_ns }`.
`CarLine` = number, driver, position, lap, speed, energy %, AM (active / used /
scenario / budget). `FocusBlock` = the selected car + nearest **running** car
ahead/behind + **position** gaps (`gap_ahead_positions` / `gap_behind_positions`)
— never seconds; a gap > 1 means cars between retired. `OUR_CAR_NUMBER` /
`_require_our_car` deleted. `get_recent_events` / `get_events_in_range` /
`get_field_am_status` ported unchanged. The tools read the **vendored
`shared.state_client`** — the commentator package has no per-package state_client
(one fewer file for students), so the seam no longer resolves `tools.state_client`.

**Snapshot (`*/commentator/snapshot.py`).** Re-aimed field-wide:
`snapshot_dict(state, selected_car=None)` pins the leading order (top 6) plus a
focus block for the selected car. Replaces Ch2's car-13 snapshot.

**Loop (`frontend/commentator_loop.py`, new).** Fork of `engineer_loop.py`. Holds
`selected_car` via `set_selection(n)` (called from the websocket `{type:"select"}`
message), tracks `prev_positions` as a dict across polls, keys lap **recaps** off
`current_leader_lap` (the field's lap, not one car's), and injects a "the fan is
watching car N (driver)" line + the focus snapshot into each trigger prompt. All
Ch2 trigger policy kept (per-type debounce, must-say hold + TTL, overdue-recap
guarantee, drop-don't-crash, replay-restart reset). Constructor takes optional
`agent_client` / `state_client` for offline testing. Deliveries broadcast as
`{type:"radio", kind, text, selected_car, ...}`.

**Seam re-point.** Ch2's `race_engineer` package was left behind, so the seam
defaults pointed at a missing package. Re-pointed: `shared/agent_pkg.py` default →
`solution.commentator`; `activate.sh` default → `starter.commentator`.

**Verification.** `scripts/verify_commentator_offline.py` proves the scorer +
frame tools + selection-aware loop against a seeded in-memory field with **no
GCP** (all checks pass). `scripts/test_frame_tools.py` retargeted to the
field-wide tools (seed + `--live`). `scripts/local_commentator.py` is the live
harness (`--select <car>` simulates the fan's click). Full live procedure:
`deploy/RUNBOOK_commentator.md`.

**Deferred to #7/#8 (noted, not built):** `frontend/main.py` still imports Ch2's
`EngineerLoop` / `OUR_CAR_NUMBER` / `tools.state_client` — swapping it to
`CommentatorLoop` + the `{type:"select"}` websocket handler is the frontend rewire
(#7); the `setup/8_deploy_cloud.sh` rename is #8/deploy. The commentator package,
loop, scorer, tools, and harness are complete and consumed by that rewire.

### Live-run findings & prompt tuning (2026-06-29, on the Qwiklabs replay)

First live run (both `local_commentator.py` modes against the Berlin R10 sim)
confirmed the design: field-wide mode spreads across leaders / AM clusters /
recaps; `--select 13` narrowed every fired call onto car 13 (each scored 110 =
70 overtake + 25 selected + 15 lead-battle, so must-say). Driver names resolved
from the frame data; the scorer's debounce visibly suppressed the long tail.
Three behaviours got tuned **in the persona/builders** (not the scorer):

1. **Latency.** Tool-using turns ran 15–25 s (vs 6–9 s otherwise) — too slow for a
   live call. The snapshot already carries the leaders + focus + Attack Mode, so
   the event-reaction builder and the DATA-DISCIPLINE prompt now say *narrate from
   the snapshot, make zero tool calls* unless a needed car is absent.
2. **Unfounded closeness.** The model used "right on his gearbox" / "breathing down
   his neck" — gap claims it can't support (positions only, no time-gaps). The
   GAPS section now bans closeness phrasing and allows only order ("up to P2") plus
   data-backed trends ("climbing" when a position actually changed).
3. **Flavour.** Added explicit licence for vivid verbs / stakes / circuit colour —
   provided every flourish rides a real fact — and a "vary your phrasing" nudge
   (the run repeated "slices past").

**Tuning levers if needed later (not changed):** select-mode is intentionally
eager — every selected-car overtake is must-say (`SELECTED_CAR_MUST_SAY_MIN=80`),
so raising that constant calms a too-chatty "my car" feed. `DEFAULT_THRESHOLD`,
`debounce_s`, and `must_say_gap_s` (loop/harness args) trade coverage for calm.
One thing to spot-check on any run: a "safety car" mention is only honest if the
snapshot's `race_phase` was actually `safety_car` — it's grounded by the prompt,
but worth confirming on a busy replay.

### Second live run — UI findings (2026-06-29, the #7 companion page)

Running the page surfaced two things, both fixed:

1. **Selection desync ("everything is car 94").** Field-wide commentary fixated on
   one car, with calls wrongly tagged must-say. Cause: `CommentatorLoop` holds ONE
   `_selected_car` for the whole server process, and it outlives a client. A car
   selected in an earlier tab/run stayed boosted; a fresh page showed "field-wide"
   but never told the server to clear (the reconnect only re-sent a *non-null*
   selection). Fix: the page now calls `sendSelection()` on every websocket open,
   including the cleared (null) state, so a fresh load resets the loop to
   field-wide. (Selection is single-fan/global by design; last client wins.)
2. **Too quiet for a broadcast.** Once the stuck must-say was gone, the 15s debounce
   left long silences. First mitigated with cadence knobs (`debounce_s` 15→8,
   `summary_every` 2→1, an `idle_filler_s`) — but that only papers over a deeper
   mismatch, addressed by the redesign below.

### Redesign — continuous play-by-play (2026-06-29) — SUPERSEDES the gate model

Tuning the debounce wasn't enough: an event **gate** is the wrong control model for
a commentator. Ch2's scorer-as-gate ("speak only when something clears a
threshold") fits a race engineer who must not distract the driver; a live
commentator's job is the opposite — keep talking, follow the front of the race.
So the commentator loop was rebuilt around the scorer as a **director**, not a gate:

- **`frontend/commentator_loop.py` is now a continuous beat.** Every cycle it reads
  the field, asks `shared.scorer.score()` to RANK what's happened since the last
  line (front-weighted via `LEAD_BATTLE_BOOST`, selected-car-boosted), and hands the
  model the top `max_lead_events` items + the running order + **the last few lines
  it said** (`recent_window`, a rolling deque). It ALWAYS emits — no threshold, no
  debounce. Paced by `reading_gap_s` (the pause after each line ≈ time to read it),
  so spacing ≈ generation time + the gap.
- **Memory without session state.** Continuity comes from feeding the recent lines
  back in the prompt (stateless, portable across local/engine), so each line
  *continues* the call instead of re-introducing the field; the persona is told not
  to repeat them. Quiet spells still produce a line (running order / storyline).
- **`shared/scorer.py` is UNCHANGED** — same ranking; only its consumer changed
  (rank-and-narrate instead of gate). `must_say` now just bubbles a safety car to
  the top of the ranking so the next line leads with it.
- **Prompts:** one builder `build_commentary_prompt(recent_lines, action_json,
  snapshot_json, watching)` replaces the old `build_event_reaction_prompt` /
  `build_lap_summary_prompt`. The persona is rewritten for a flowing stream that
  leads with the front of the field and narrows onto the selected car.
- **Reading, not audio.** Designed for on-screen reading (TTS is an optional toggle,
  default muted — a room of 50 laptops shouldn't all talk). That removes the
  ~7s-per-clip audio ceiling and lets each line be 2-3 flowing sentences.
- **Knobs:** `CommentatorLoop(reading_gap_s, max_lead_events, recent_window)`;
  harness `--reading-gap` / `--lead-events` / `--recent-window`. The old
  `debounce_s` / `must_say_gap_s` / `summary_every` / `idle_filler_s` are gone.
- **Cleanup:** `frontend/engineer_loop.py` and `scripts/local_test.py` (Ch2's
  gate-model loop + harness) are superseded → tombstoned, safe to `git rm`.

**Teaching beat:** "an engineer speaks only when it matters; a commentator never
shuts up — so the deterministic code's role flips from *gatekeeper* to *director*."
A cleaner Ch1-distinct lesson than re-teaching Ch2's gate.
