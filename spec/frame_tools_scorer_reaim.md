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
