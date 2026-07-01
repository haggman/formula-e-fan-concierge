# Build the Formula E Race-Day Companion

You're going to build the AI that brings a live race to life for fans. By the end
you'll have **two voices** running on a real second-screen app over the 2024
Berlin E-Prix:

1. **An AI Commentator** — an agent you build in Python that calls the race
   play-by-play and follows whichever car the fan is watching.
2. **A Fan Concierge** — a low-code chat bot you build in the console that
   answers anything a fan asks, grounded in real data and without spoilers.

Everything the two voices sit on top of — the live race feed, the track map, the
data — is already running for you. **You build the voices.**

The plan: spend roughly the first two-thirds of your time on the **Commentator**
(it's the meaty, hands-on agent build), then the rest on the **Concierge**.

---

## STEP 0 — do this FIRST, before the presenter starts talking

The build machine takes a minute to wake up. Kick it off now so it's ready when
you are.

1. Open **Cloud Shell** from the Google Cloud console (the `>_` icon, top right).
2. Get the code and enter it:
   ```bash
   cd ~/formula-e-fan-concierge      # already cloned for you; if not, ask the presenter
   source activate.sh                # sets up your Python env — takes ~30s the first time
   ```
   `source activate.sh` is the one command you'll run in **every new terminal
   tab**. If anything ever complains about a missing module or environment, this
   is the fix.
3. Confirm the race is live (the presenter deployed the whole stack before the
   event):
   ```bash
   python setup/verify_checks.py
   ```
   You want to see **"RaceState fresh"**. That means the race is replaying and
   flowing into the database — you're ready.

Now sit back for the intro.

---

## What you're building

The finished product is one page with three regions and a chat bubble:

- a **track map** with a dot per car,
- a **field strip** across the top showing the running order and the gaps,
- a scrolling **live commentary feed** — that's your Commentator talking,
- and a **chat bubble** in the corner — that's your Concierge.

You'll build the Commentator first and watch it drive that whole page. Then
you'll build the Concierge and drop it into the corner.

**Before you write anything, read `HOW_IT_WORKS.md`** (ten minutes). It explains
what a "frame" is, why the commentator never goes quiet, and which files are
yours versus plumbing. The rest of this guide assumes you've read it.

## Two minutes of Formula E (so your commentary makes sense)

- **The race:** ~22 electric cars, ~45 minutes, street circuit at Berlin's old
  Tempelhof airport. Cars have a **position** (P1 = leading) and a **lap**.
- **Attack Mode:** a driver can arm a temporary **~50 kW power boost** by driving
  through an activation zone — a tactical weapon (they get a fixed budget of
  seconds, split across activations). When a car takes Attack Mode, expect it to
  attack. This is the single most-commentated tactical moment in FE.
- **Energy:** every car manages a battery; running out means slowing dramatically.
- **What you *don't* have:** time-gaps in seconds between cars. You have
  **positions and order**. So your commentator talks in places ("up to P2",
  "leading car 94"), never invented seconds.

## A five-minute ADK primer

You'll build the commentator with **Google's Agent Development Kit (ADK)** and a
**Gemini** model. The whole idea of an ADK agent is small:

```python
from google.adk.agents import Agent

root_agent = Agent(
    name="commentator",
    model="gemini-3.5-flash",
    instruction="<the personality + rules you write>",   # this is where the work is
    tools=[...],                                          # functions the agent may call
)
```

- The **instruction** (a.k.a. the persona/system prompt) is *most of the job* —
  it decides how the agent behaves.
- **Tools** are plain Python functions the agent can call to look things up. The
  agent reads each tool's **docstring and type hints** to decide when to call it
  and what to pass — so the docstring *is* the tool's contract.
- The **model** does the language; your instruction and tools shape what it does.

That's it. You'll spend your time on the instruction.

## Your workspace — a tiny, self-contained agent

Your entire commentator lives in **two files** — deliberately small, so you're
never hunting through the codebase:

| File | What you do |
|---|---|
| `starter/commentator/prompts.py` | **the main event** — write the broadcaster persona |
| `starter/commentator/agent.py` | one short step — wire your agent together |

Everything else in `starter/commentator/` (the live-race tools, the config) is
given and marked so — you don't edit it.

**Three ways to run and test your agent, smallest to biggest:**

```bash
# 1. Prove the live-race tools work against the real feed (a sanity check):
python scripts/test_frame_tools.py --live

# 2. Watch YOUR commentator call the race in your terminal (your main test loop):
python scripts/local_commentator.py --duration 120
python scripts/local_commentator.py --select 13 --duration 120   # follow car 13

# 3. Run the whole companion page (the final step):
bash demo.sh                       # then open Web Preview on port 8080
```

**Stuck at any point?** The finished reference agent is right there. Run it to see
the target, then go back to yours:

```bash
AGENT_PACKAGE=solution.commentator python scripts/local_commentator.py --duration 120
```

And you can read the reference persona in `solution/commentator/prompts.py` — but
try your own first; that's where the learning is.

---

# The build — one layer at a time

You'll grow your commentator from "barely talks" to "on the air," adding one
capability per challenge. Each challenge ends in something you can *see working*.

## Challenge 1 — Get your commentator talking (~20 min)

**Goal:** the simplest possible agent that produces commentary.

**Do this** in `starter/commentator/`:

1. In `prompts.py`, write a first draft of `ROOT_AGENT_INSTRUCTION` — just a
   sentence or two: *"You are a live Formula E TV commentator. Describe what's
   happening in the race in an exciting way."* Don't polish it yet. Fill in a
   one-line `ROOT_AGENT_DESCRIPTION` too.
2. In `agent.py`, build `root_agent`: an `Agent` with `name`, `model=MODEL`,
   `generate_content_config=shared_config`, your `description` and `instruction`,
   and — for now — `tools=[get_field_state, get_recent_events,
   get_events_in_range, get_field_am_status]` (they're already imported for you).

**Test it (your milestone):**
```bash
python scripts/local_commentator.py --duration 90
```
Your terminal should print commentary lines every few seconds. It won't be
polished — it might be flat or repetitive — but **your agent is calling a real,
live race.** That's the milestone.

**Stuck?** Compare against
`AGENT_PACKAGE=solution.commentator python scripts/local_commentator.py`, and
peek at `solution/commentator/agent.py` for the exact wiring.

## Challenge 2 — Give it a broadcaster's voice (~30–40 min)

**Goal:** turn a robot reading facts into a commentator you'd actually listen to.
This is the heart of the whole build — it's almost entirely in
`ROOT_AGENT_INSTRUCTION`.

**Do this:** rewrite your instruction so the commentator:

- **Talks in third person** about the field — "car 5 is through on car 6" — never
  "we"/"you", never a single driver's radio.
- **Leads with the front of the race** — the lead battle and the top few — then
  drops down the order for a big move, then comes back to the front.
- **Flows.** Each turn it's shown *the last few lines it said* and the newest
  action; it should *continue* the call, not restart it or repeat itself.
- **Stays honest.** Only facts it's given. Positions and order, **never a gap in
  seconds** and never "right on his gearbox" closeness (you don't have that data).
- **Brings energy** — vivid verbs, a sense of stakes — but every flourish sits on
  a real fact.
- **Is speakable** (it can be read aloud): plain sentences, digits not words
  ("P3", "50 kilowatts"), no markdown.

**Test it (your milestone):**
```bash
python scripts/local_commentator.py --duration 150
```
Read the output as a transcript. It should read like a broadcast — flowing,
front-of-race, no invented gaps. Compare a run of yours against the reference to
gut-check the voice.

**Stuck?** `solution/commentator/prompts.py` is the reference persona. Skim its
structure (VOICE / what to talk about / honesty), then write yours in your words.

## Challenge 3 — Follow the fan's car (~20 min)

**Goal:** when a fan picks a car, the commentary *narrows onto it*. This is the
feature that makes it a companion, not a broadcast.

**How it works:** when a car is selected, the loop tells your agent by putting a
line in the prompt — *"THE FAN IS WATCHING car 13"* — and includes a **focus
block** (that car plus its nearest rivals). Your persona just has to *use* it.

**Do this:** add a rule to `ROOT_AGENT_INSTRUCTION`: *when the prompt says a car
is selected, lead with that car and its battle every line — where it sits, who
it's fighting, what just changed for it — then glance at the front. When no car
is selected, cover the front of the field.*

**Test it (your milestone):**
```bash
python scripts/local_commentator.py --select 13 --duration 150
```
Every line should now open on car 13 and its fight. Run it again without
`--select` and confirm it goes back to covering the whole field.

**Stuck?** The reference handles this in the same instruction file — search it for
"WATCHING".

## Challenge 4 — Put it on the air (~15 min)

**Goal:** your commentator drives the real companion page — map, field strip,
live feed, click-to-follow, and (optionally) spoken aloud.

**Do this:**
```bash
bash demo.sh
```
Then open **Web Preview on port 8080** (the toolbar button in Cloud Shell).

**Test it (your milestone):**
- The track map shows the cars going round; the field strip shows the order.
- The **live commentary feed** on the right is *your* commentator, calling the
  race continuously.
- **Click a car** on the map or in the order — the commentary narrows onto it
  (and the strip marks it). Click "× field-wide" to go back.
- Click **🔊 LIVE AUDIO** (top right) to hear it spoken.

That's the whole product running on the agent you built. 🎉

**Stuck?** `RUN_SOLUTION=1 bash demo.sh` runs the same page on the reference
commentator, so you can compare side by side.

---

## Challenge 5 — Build the Fan Concierge (~45–60 min)

Now the second voice — the **ask-anything** chat bubble. This one is **low-code**:
you build it in **CX Agent Studio** in the console, not in Python. It answers a
fan's questions — live ("how's car 13 right now?"), historical ("tell me about
Vandoorne"), the rules ("what's Attack Mode?"), and general knowledge — always
from real tools, and it **refuses spoilers** ("who wins?").

The full click-by-click walkthrough is
**`solution/cx_concierge/BUILD_CONCIERGE.md`** — follow it. In short, you'll:

1. Create a fan-concierge agent in CX Agent Studio and give it a fan-voiced,
   spoiler-safe persona.
2. Wire its three tools, one at a time, testing after each in the built-in
   Simulator:
   - **`google_search`** — current / real-world / off-race questions.
   - **`ask_race_data`** — an OpenAPI tool pointing at the **given** race-data
     service, for anything about *this* race (live state + in-race stats),
     time-honest so it can't spoil.
   - **`fe_knowledge`** — the data stores of driver/team profiles + the rulebook.
3. Deploy it as a **web widget** and confirm it answers.

**Test it (your milestone):** in the Simulator, ask:
- "How's car 13 right now?" → answers from the live race.
- "Tell me about Nick Cassidy." → answers from the profiles.
- "Who wins the race?" → **refuses** (that's the design).

**Optional — embed it on the companion page.** `index.html` has two clearly
marked slots (a HEAD slot and a BODY slot) for the widget's snippets. Paste them
in and the bubble appears in the corner next to your commentator. (Ask the
presenter — the reference companion already has this wired.)

---

## Stretch — make it yours

Time left? Pick one:

- **Tune the director.** `shared/scorer.py` decides what your commentator talks
  about. Nudge the weights — make Attack Mode louder, make the lead battle
  dominate, calm a too-chatty selected-car feed (`SELECTED_CAR_MUST_SAY_MIN`).
- **Change the cadence.** In `frontend/commentator_loop.py`, `reading_gap_s` sets
  how fast the commentary flows.
- **A second persona.** Give the commentator a different character (a hyped-up
  hype-caller, a dry tactician) and A/B them.
- **Deepen the concierge.** Add a tool, or tighten its instructions so answers
  never garble.

---

## Question bank (to test your agents)

**Commentator** (watch the feed after each):
- Restart the race from the grid and watch the opening-lap shuffle.
- Select the leader, then select a mid-pack car — does the focus follow?
- Wait for an Attack Mode activation — does it call it as a tactical moment?

**Concierge** (in the CX Simulator or the bubble):
- "Who's leading right now?" · "How much energy does car 13 have?"
- "What's Attack Mode?" · "Tell me about DS Penske."
- "Who won the Berlin 2024 E-Prix?" → must refuse.

## When things go sideways

- **"No module named…" / env errors** → you forgot `source activate.sh` in this tab.
- **No RaceState / empty feed** → the race isn't playing. In the page's SIM bar
  hit **RESTART**, or ask the presenter to restart the simulator.
- **Commentary is blank or errors** → check your `agent.py` builds `root_agent`
  (not `None`) and that your `instruction` isn't empty.
- **It invents seconds or says "on his gearbox"** → tighten the honesty rule in
  your persona (positions only).
- **Model "429 / resource exhausted"** → try
  `export FE_MODEL=gemini-2.5-flash GOOGLE_CLOUD_LOCATION=us-central1` and re-run.
- **The concierge bubble won't load** → give it a few seconds (the SDK loads from
  Google); confirm the deployment's **Public Access** is on.

## Finished early?

You built two production-shaped agents — a custom live commentator and a managed
grounded concierge — on one product. Go tune the stretch goals, or open
`HOW_IT_WORKS.md` and trace how a single click travels from the map, through the
loop, to a line of commentary.
