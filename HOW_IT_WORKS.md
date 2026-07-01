# How it works — the ten-minute orientation

Read this before you start building. It answers the questions the codebase
assumes you've already asked: what's replaying, what you build versus what's
given, why the commentator never shuts up, and how a fan's question gets a
grounded answer. Python knowledge assumed; nothing else.

## The system in one paragraph

A recorded Formula E race — the **2024 Berlin E-Prix, Round 10** — replays
through your project as if it were live. A **simulator** publishes one JSON
*frame* per race-second to Pub/Sub; a **State Writer worker pool** turns each
frame into Firestore documents — that's the **"now."** The same race's full
timing history, plus ten seasons of driver and team careers, sit in **BigQuery**
behind an **MCP Toolbox** of query tools — that's the **"then."** A given
**race-data subagent** (ADK) owns both worlds and is *time-honest* — it never
looks past the replay's current moment. On top of all this sits a given **fan
companion UI**: a live track map, a running-order **gap strip**, and a scrolling
commentary feed. You build the **two voices** that bring it to life:

- **The Commentator** (ADK, you write it) — calls the race play-by-play and
  narrows onto whichever car a fan clicks.
- **The CX Concierge** (low-code, you build it in CX Agent Studio) — the chat
  bubble that answers anything a fan asks, grounded and spoiler-free.

Everything the two voices *depend on* — the data plane, the subagent, the
knowledge stores, the frontend — is stood up for you (the instructor stack).
You build the voices.

## What is a frame?

One snapshot of the entire race at one race-second (heavily trimmed):

```json
{
  "race_time_s": 193,
  "race_phase": "racing",
  "cars": [
    {"car_number": 13, "driver_short_name": "DAC", "position": 6,
     "current_lap": 3, "speed_kmh": 140.3,
     "gps": {"lat": 52.4811, "lng": 13.3910},
     "energy": {"pct_remaining": 93.05},
     "attack_mode": {"active": false, "activations_used": 0,
                     "scenario": 2, "remaining_budget_s": 240.0}},
    "... 21 more cars ..."
  ],
  "events": [{"type": "overtake", "car_number": 13, "...": "..."}]
}
```

The State Writer splits each frame in two: the whole frame overwrites **one**
Firestore doc, `race_states/berlin_2024_r10` (the current state of the world),
and each item in `events[]` becomes its own doc in `race_events/` (the queryable
recent past). Writes are idempotent (deterministic event IDs), so replays and
Pub/Sub redelivery converge instead of duplicating. Curl `$SIM_URL/schema` any
time to see a real, complete frame.

## Two voices, one race

The whole product is **one screen, two ways of talking to a fan**:

| | **Commentator** (you build, ADK) | **Concierge** (you build, CX low-code) |
|---|---|---|
| Mode | **PUSH** — talks *at* you, continuously | **PULL** — answers *when* you ask |
| Surface | the scrolling live commentary feed | the chat bubble, bottom-right |
| Knows | the live race ("now") | now + history + rules + the wider world |
| Reads | Firestore "now" via given frame tools | the subagent, the knowledge stores, Google Search |

They are not two chatbots. The commentator is a *broadcaster*; the concierge is
the *ask-anything bot*. Composing a **custom live agent** next to a **managed
CX bot** on one surface is the whole point.

## What makes the commentator talk

A real broadcaster is *never quiet* — they keep a running story going and lean in
when something happens. That's the design here, and the important part is that
**the model never decides when to speak.** A deterministic loop does.

`frontend/commentator_loop.py` runs a continuous beat:

1. **Read** Firestore "now" (the field) and the events since the last line.
2. **Rank** them with `shared/scorer.py` — pure, deterministic weights
   (overtakes, Attack Mode, position swings, race control), **boosted toward the
   front of the field and toward the car the fan has selected.**
3. **Narrate** — hand the model the top action + the running order + *the last few
   lines it just said*, and get back 2–3 flowing sentences that continue the call.
   It emits on every beat.

> **The idea to take away:** because the commentary never goes quiet, the
> deterministic code's job isn't to decide *whether* to talk — it's to decide
> *what to talk about*. The code picks the facts; the model chooses the words.

**Selection** is the distinctive beat. A fan clicks a car → the UI sends
`{type:"select", car_number}` over the websocket → the loop boosts that car in
the scorer and tells the model to lead with it. Click away → back to the whole
field. The commentator "follows what you're watching."

**Honesty:** it narrates only from the snapshot the loop pins for it. It speaks
in *positions and order* — never a gap in seconds, because we have GPS positions,
not time-gap telemetry.

## The journey of a fan's question

A fan taps the concierge bubble and asks "how's car 13 right now?" The **CX
concierge** is an *orchestrator* — it picks a tool and answers from it, never
from its own memory:

- **Live / in-race** ("how's car 13 now?", "who's leading?") → `ask_race_data`
  (an OpenAPI tool → the given **subagent** → Firestore "now" / BigQuery "then").
- **Drivers, teams, rules** ("tell me about Vandoorne", "what's Attack Mode?") →
  `fe_knowledge` (the RAG data stores).
- **Current / real-world / off-dataset** → `google_search`.

And it's **time-honest**: ask "who wins?" and it refuses — the subagent only
sees up to the replay's current moment, and the persona closes the Google-Search
spoiler back-door too. That refusal is the design, not a limitation.

Meanwhile the commentator keeps pushing its feed, and every panel — the map
dots, the gap strip, the running order — rides the same 1 Hz state broadcast
over the websocket. Two voices, one race, one screen.

## The file map

**YOURS — the two voices:**

| Voice | Where | What you do |
|---|---|---|
| Commentator | `starter/commentator/prompts.py` | **the main lesson** — author the broadcast persona (third-person, front-of-field, selection-aware, honest) |
| Commentator | `starter/commentator/agent.py` | one short wiring step — build `root_agent` from your persona + the given tools |
| Concierge | CX Agent Studio (in the console) | build the agent, wire its 3 tools, ground it, embed the widget — walkthrough in `solution/cx_concierge/BUILD_CONCIERGE.md` |

**READ THESE — given, but worth your time:**

- `starter/commentator/tools/frame_tools.py` — the field-wide live tools
  (`get_field_state(selected_car)` + friends). Given infrastructure; you register
  them, you don't write them.
- `shared/scorer.py` — the director. Field-wide significance + the selected-car
  boost. Read it to understand what your commentary is handed each beat.
- `frontend/commentator_loop.py` — the continuous beat (poll → rank → narrate),
  and how selection threads through.
- `shared/models.py` — the Pydantic contract for RaceState/Event.

**PLUMBING — works, ignore unless curious:**

`frontend/` (the companion UI, the loop, TTS) · `state_writer/` (the worker pool)
· `simulator/` · `race_data_subagent/` (the given time-honest subagent) ·
`cx_concierge/grounding/` (the authored profiles + rules) · `setup/` and
`deploy/` (idempotent provisioning) · `scripts/` (test harnesses — run them,
don't edit them) · `notebooks/` (one-time data prep) · `solution/` (the answer key).

## Five facts that will save you a debugging hour

1. **Every new Cloud Shell tab needs `source activate.sh`.** It sets your venv,
   `PROJECT_ID`, and `AGENT_PACKAGE`. Env/venv complaints are always this.
2. **Stuck on the commentator? Flip the seam.** `AGENT_PACKAGE=solution.commentator`
   runs the reference; `solution/commentator/prompts.py` is the answer key. Your
   build is `starter.commentator` (the default).
3. **The commentator narrates from the snapshot — with essentially zero tool
   calls.** The loop hands it the moment; it's a *live* call, so speed matters and
   it speaks in positions, never invented seconds.
4. **Build and test at 2×, demo at 1×.** At high replay speed the model's thinking
   lags the race — lines get stale, not wrong.
5. **The CX widget loads its SDK from `gstatic.com` and needs the deployment's
   *Public Access* on.** Give it a couple of seconds to show the bubble. The
   fastest place to test the concierge's *answers* is the Simulator inside CX
   Agent Studio, before you ever embed it.
