# Challenge 1 — The Agentic Fan Concierge · Planning Document

_Working document. This is the thing we plan around; it is not the build. Decisions
marked **[OPEN]** are deliberately unresolved and become the agenda for the spin-off
conversations listed at the end._

Status: **draft v1** · Companion build: Challenge 2 lives in `../formula-e-race-engineer/`

---

> **Direction update (v2, this session):** the concept has firmed up around the
> **Race-Day Companion** — see **§9**, which is now the canonical concept and supersedes
> the more CRM/segmentation-heavy framing in §1–§4 below. §1–§5 are kept for the data map,
> reuse map, and reasoning that still hold.

## 1. What we're building (the concept)

A Formula E **Fan Concierge** for the Berlin 2024 E-Prix replay: a fan-facing companion
with **two surfaces and one brain**, personalized to a single fan profile.

1. **The Concierge Feed — the agent reaches out (proactive / push).**
   As the race replays, the agent decides what *this fan* should be told and pushes
   cards/notifications to their feed: their favourite driver's moves ("Evans just took
   Attack Mode"), battles worth watching, energy drama, "head to Turn 6 now" itinerary
   nudges. Personalized by the fan's profile — favourite driver/team, persona archetype
   from the segmentation research, stated interests.

2. **The Concierge Chat — the agent answers (reactive / pull).**
   A conversational agent the fan asks anything: "What's Attack Mode?", "Tell me about
   Mitch Evans", "Who should I watch today?", "Build me a Saturday itinerary." Grounded
   via retrieval over driver bios, team history, and a curated FE-rules pack, fused with
   BigQuery career/results data — no invented rules, no invented stats.

3. **The write-back — the agent acts (the agentic loop).**
   What the fan does — asks about Evans, taps a card, states a preference — updates their
   profile in a **simulated CRM**, which changes future pushes. The concierge doesn't just
   answer; it *learns and acts on* the fan's world. This is the brief's "execute API calls
   to update the fan's profile … ensuring their preferences dictate future interactions."

This is the brief's "Agentic Fan Concierge" rendered as a real consumer product surface
rather than a dashboard — which is also what makes it fun to build.

### Why it lands for a developer audience (the "sexy" test)
- A real **agentic product**, not a chart: an agent that reaches out, answers, and writes state.
- **RAG done right** — grounded Q&A over a managed data store, with honest refusals.
- **Function-calling that mutates state** (the CRM write) with a guardrail/approval gate.
- **Proactive push driven by a deterministic relevance scorer** — code decides *who/when*,
  the model decides *what* (the Ch2 doctrine, re-aimed at fan relevance).
- An optional **BigQuery ML** tier (fan segmentation / "drivers you'd like" recommender)
  for the data-science-curious — a genuinely fun stretch.

---

## 2. The teaching spine (the hero beat)

Every student should walk out able to say:

> **"A concierge has two faces — it reaches out and it answers — and both are only as good
> as how well it knows *this* fan and how honestly it sticks to the facts."**

Three transferable lessons hang off that, each earned by a tier that fails before it fixes
(the Ch2 pedagogy: watch the lie, then build the fix):

1. **Grounded conversation.** RAG so rules and bios are real, not hallucinated — the fan
   chat's honesty doctrine. (Direct descendant of Ch2's "ungrounded model is a podcast.")
2. **Proactive agency with restraint.** A good concierge personalizes and *doesn't spam*;
   code decides who/when, the model writes what. The fan-side echo of Ch2's negative space.
3. **An agent that acts.** The CRM write-back closes the loop — preferences in, behaviour
   changed out — with a human-in-the-loop guard on the state change.

---

## 3. Architecture & the Ch2 reuse map

The single biggest lever on our build cost is how much of the Challenge 2 chassis we lift.
The good news: the two-surface concept reuses a lot.

### Reuse from `formula-e-race-engineer/` (lift, lightly adapt)

| Component | Ch2 role | Ch1 use |
|---|---|---|
| Simulator → Pub/Sub → Firestore live "now" | feeds the pit wall | feeds the **push feed** — same live race state, new consumer |
| BigQuery `fe_race10` + 10-season career/results | the "then" | driver profiles, "who to watch," career fusion in chat |
| MCP Toolbox curated tools | 14 BQ tools | many transfer (lap history, overtakes, driver lookup, career stats); add fan-facing ones |
| The deterministic **scorer / trigger** pattern | decides when the engineer speaks | retune weights for **fan relevance** (per-fan, persona-weighted) instead of engineer urgency |
| `setup/` + `deploy/` numbered scripts, `activate.sh`, verify pattern | event setup | same skeleton, new services bolted on |
| The doc suite shape (Student Guide / Run of Show / Demo / How It Works) | event delivery | mirror it for Ch1 |

### New build for Ch1

| Component | What it is | Notes |
|---|---|---|
| **Fan profile / simulated CRM** | Firestore collection + a Cloud Function "CRM API" the agent calls | the write-back target; seeds from segmentation personas |
| **RAG knowledge base + data store** | driver bios + team history + curated FE-rules pack → Vertex AI Search (or a vector store) | **[OPEN]** which retrieval backend |
| **Fan-facing UI** | the feed + chat surface | distinct from the pit wall; **[OPEN]** new app vs lightweight template |
| **Per-fan relevance scorer + push delivery** | reweighted scorer + a delivery path to the feed | "your driver" boosts; debounce so it doesn't spam |
| **The conversational chat agent** | the pull surface | **[OPEN]** CX Conversational Agents vs ADK chat (see §5) |

### Sketch (one fan, one race replay)

```
[Ch2 simulator] → Pub/Sub → Firestore "now" ─┐
                                              ├─→ [Relevance scorer (per-fan)] → [Push agent: writes feed cards]
[Fan profile / CRM (Firestore)] ─────────────┘                                          │
        ↑ write-back (Cloud Function CRM API)                                            ▼
        │                                                                          [ Fan UI: Feed ]
[Chat agent] ──→ RAG data store (bios, team history, rules pack)                   [ Fan UI: Chat ]
        └──────→ MCP Toolbox → BigQuery (career, results, race history)
```

---

## 4. The student day — candidate tier ladder (~75 min, one agent grows)

Mirrors Ch2: one agent built in place, never thrown away; each tier ends in something
demoable and a failure that motivates the next tier. Budgets are first-draft.

- **Tier A — Stand up the concierge (~15).** Create the agent; load one fan profile into
  context; ask it about rules and drivers. It answers confidently and *wrong* — invented
  rules, invented stats. (Same A-lesson as Ch2: ungrounded = podcast.)
- **Tier B — Ground the chat: RAG over the knowledge base (~20).** Wire a retrieval tool /
  data store over driver bios + the FE-rules pack. "What's Attack Mode?" is now grounded and
  cited. The failure→fix: the invented rule becomes a real one.
- **Tier C — Curate the data tools (~15).** Wire the Toolbox so "Tell me about Evans" /
  "who should I watch" pull real career numbers and results, not vibes. (Reuses Ch2 tools.)
- **Tier D — Go live + personalize the feed (~25).** Adopt the live plane (Firestore "now");
  build the per-fan relevance scorer and push the feed. The fan's favourite driver taking
  Attack Mode fires a personalized card. Two worlds (now + then), fan-personalized.
- **Tier E — Close the loop: CRM write-back + concierge persona (~30).** A function-call
  updates the fan profile (with a guardrail/approval), and the concierge gets a voice tuned
  to the fan's segment. The behaviour change is visible: future pushes shift.
- **Tier F — Make it yours (stretch).** BigQuery ML fan segmentation or a "drivers like
  yours" recommender; new notification rules; a multi-persona demo; an itinerary generator
  using the circuit map + day-by-day schedule.

---

## 5. Data map (asset → use)

All assets staged under `gs://class-demo/formula-e/`; see
`../formula-e_reference_data_dictionary.md` and `..._data_manifest.json`.

| Asset | Feeds |
|---|---|
| `fan_segmentation/electric_generation_overview.pdf` + `..._update_oct_2023.pdf` | personas, profile seeds, concierge persona/voice |
| `race_results/driver.parquet` (87 drivers, careers) | driver profiles, "who to watch" |
| `race_results/race.parquet`, `race_statistics.parquet` (10 seasons) | career/results fusion in chat (BQ) |
| GCS driver bios + team history (unstructured) | **RAG knowledge base** |
| `reference/circuit_plan_v2.pdf` + `day_by_day_r09/r10.pdf` | itinerary building, "head to Turn X" nudges |
| Berlin 2024 live data (sim → Firestore) | the **push feed** "now" |
| `fanbotv2/HD_v02.mp4` | **investigate** — possibly an existing FE fan-bot reference/inspiration |

### Data gaps to resolve early (confirmed by manifest investigation, v1)
Two things the brief assumes are **not in the staged dataset**:

1. **No FE rules/regulations document.** Only the data dictionary's "Resolved Findings"
   (Attack Mode = +50 kW, two activations, 240 s budget, scenarios, energy normalization,
   race format), the summary metadata (circuit, AM zone), the circuit map, and schedules.
2. **No driver-bio or team-history corpus.** The brief lists "driver bios, team history" as
   unstructured GCS docs, but there are none. The only driver/team data is **structured** —
   the entry list (`drivers.parquet`: name, team, manufacturer, hometown, country) and career
   stats (`driver.parquet`, `race.parquet`).

**Implication:** the chat's RAG knowledge base is something we **build**, not something we
point at. We author a curated **knowledge pack** — a rules pack (Resolved Findings are a
strong seed) plus driver/team bios synthesized from the structured data (and public info) —
and load that into the data store. This makes decision #6 effectively "yes, we author it"
and reshapes work item #2 from "assemble + index" to "author + index."

---

## 6. Decision register (reconciled after the architecture conversation)

_Source of truth for the resolved architecture: `ARCHITECTURE_BRIEF.md` ("Resolved this
session") and `spec/`._

1. **[RESOLVED] Engines — three, not "CX vs ADK".** A **CX** orchestrator (`cx_concierge`,
   low-code) + an ADK **commentator** + an ADK **race-data subagent**. The "two engines as a
   feature" idea became three, with a clean team split.
2. **[OPEN → leans Vertex AI Search] RAG backend.** Settle in the Knowledge-Base & RAG
   conversation; profiles + rules pack must be **authored** (see §5).
3. **[RESOLVED] Live-plane reuse — full.** Reuse sim → Pub/Sub → Firestore; **state writer →
   Cloud Run Worker Pool (Pub/Sub pull)**. (`spec/state_writer_worker_pool.md`.)
4. **[PARKED → stretch] BigQuery ML.** Tier F / data-science stretch, not core.
5. **[RESOLVED] Front end is given.** Adapt the Ch2 UI — track map + car-select + live stats
   panel + CX widget; selection travels over the websocket. Students build backend agents.
6. **[RESOLVED → author it] Knowledge source.** No rules doc / bio corpus in the dataset (§5);
   author a curated pack (rules + profiles) for `cx_concierge`. Depth TBD in the KB/RAG convo.
7. **[RESOLVED by v2] Personalization = selected car.** Replaces the old single-vs-multi-fan
   question; no fan CRM/segmentation in core.
8. **[CLOSED] `fanbotv2/HD_v02.mp4`.** Viewed — it shows the car/stats, not a fan app; not
   useful. Dropped.
9. **[RESOLVED 2026-06-19 by the spike — validated live] CX → subagent transport.** The subagent is an **ADK agent on Cloud Run that serves its own `POST /ask_race_data` OpenAPI endpoint** (via `get_fast_api_app()`); CX reaches it with an **OpenAPI tool**, **Service Agent ID Token** auth (`run.invoker` on `service-{PROJECT_NUMBER}@gcp-sa-ces.iam.gserviceaccount.com`). Proven end to end in the CX simulator. The previously-favored "Agent Registry / A2A" path is **not consumable by CX** (the live CX tool menu has no A2A/registry tool type — its consumers are an ADK code orchestrator or the Gemini Enterprise app), and **Agent Engine can't serve a custom OpenAPI path** (reachable only via the `reasoningEngines` API). MCP-on-Cloud-Run works too but adds the MCP model for no student payoff. **Agent Engine + Agent Registry auto-registration + an A2A door (`to_a2a`, ~1 line) are kept as an optional showcase tier**, not the wire. (`spec/cx_integration_spike.md`.)
10. **[RESOLVED] Subagent scope.** Owns Firestore "now" + BigQuery "then", **time-honest** (bounded to the replay's current moment), over R10 + the full 10-season career data.
11. **[OPEN — minor] `gcloud run worker-pools` deploy verb** — confirm at build time.
12. **[OPEN — only if wanted] Integration Connector → Firestore** (#2b) — only needed for the
    optional direct-connector contrast; not on the critical path.

---

## 7. Work breakdown — spin-off conversations (reconciled)

Each is its own focused conversation; this doc + `spec/` are the shared reference.

| # | Conversation | Status | Notes / depends on |
|---|---|---|---|
| 1 | **Architecture & infra reuse** | ✅ done | repo skeleton, transport, scopes locked; `spec/` |
| 2 | **CX integration spike** | ✅ done (validated live) | wire = CX OpenAPI tool → ADK on Cloud Run (`POST /ask_race_data`); ref `spike/cx_openapi_spike/`; `spec/cx_integration_spike.md` |
| 3 | **`race_data_subagent` build** | ✅ done (verified live 2026-06-20) | ADK + Toolbox/BQ + real `now_tools`, time-honest; Cloud Run via `get_fast_api_app()` (LLM) / plain FastAPI (deterministic) + `POST /ask_race_data`; private deploy + `run.invoker` to `gcp-sa-ces`. Deploy: `setup/7_deploy_subagent.sh`; verify: `deploy/RUNBOOK_race_data_subagent.md` (+ §3.5 mid-race jump/pause demo); CX wiring: `solution/race_data_subagent/CX_SETUP.md`. Live E2E confirmed: grounded live-moment answer + mid-race spoiler refusal |
| 4 | **`commentator` build** | ✅ done (verified offline; live runbook ready) | ADK broadcaster, third-person field-wide POV, narrows to the selected car; forked from the Ch2 engineer (Toolbox dropped — narrates live "now" only, no BQ). **Continuous play-by-play** (redesigned from event-gate → scorer-as-director; flowing 2-3 sentence lines paced to reading time, memory via rolling recent lines, front-of-field weighted, narrows to selected car). Built: `solution/commentator/` (agent/prompts/config/snapshot/frame_tools) + `frontend/commentator_loop.py` (`set_selection()`, `build_commentary_prompt`) + `starter/commentator/` (student surface = persona + agent wiring; tools/loop/scorer given). Verify: `scripts/verify_commentator_offline.py` (no GCP, all pass) → live `deploy/RUNBOOK_commentator.md`. Deferred to #7/#8: `frontend/main.py` swap + `{type:"select"}` wire + `setup/8` rename |
| 5 | **`cx_concierge` build** | ✅ done (built + validated live) | CX orchestrator assembled with 3 tools — `ask_race_data` (OpenAPI → subagent), `fe_knowledge` (one data-store tool over both stores), `google_search`; grounded + time-honest, **spoiler-robust even via Google Search** ("who won Berlin 2024?" refused). Single build guide: `solution/cx_concierge/BUILD_CONCIERGE.md` (built incrementally one tool at a time). Citations work; fused multi-tool answers supported. |
| 6 | **Knowledge base & RAG** | ✅ done | Rules pack authored (FIA S10 PDFs + concise pack) + **comprehensive** driver/team profiles (all 87 drivers + 52 teams) generated by `cx_concierge/grounding/build_profiles.ipynb`, grounded in the career/results tables, verified 5 ways (structural, identifier, coverage, spoiler-free, LLM judge). Staged to `gs://class-demo/formula-e/grounding/` (.txt + parquet + jsonl); catalog updated. Two Vertex AI Search data stores built in CX. |
| 7 | **Frontend adaptation** | 🟡 companion page done (map + CX widget = follow-ons) | Pit wall → **Race-Day Companion**: `frontend/main.py` runs `CommentatorLoop`; field-wide `ui_state`; clickable car list → `{type:"select"}` → `set_selection()`; selected-car live stats panel; spoken commentary feed (TTS). `frontend/static/index.html` reworked. Run: `uvicorn frontend.main:app` + Web Preview 8080 (`deploy/RUNBOOK_commentator.md` §4). **Track map BUILT** (GPS-derived): `notebooks/track_map_outline.ipynb` derives the Tempelhof SVG + projection transform from R10 20 Hz telemetry (validated — clean Tempelhof); the page renders it upper-left with a click-to-select dot per car (GPS in the state payload, projected via the saved transform). Activate by dropping the notebook's `track_outline.json` into `frontend/static/`. Layout: map UL · running-order+selected-stats LL · continuous commentary full-height right · ask+sim bottom. Deferred: CX chat-widget embed (placeholder in index.html — the "add the chatbot" bonus); `setup/8` Cloud Run deploy = #8 |
| 8 | **State writer → Worker Pool** | ✅ done (confirm `gcloud` verb at deploy) | Converted push service → Cloud Run Worker Pool (Pub/Sub pull). `state_writer/writer_core.py` (idempotent domain logic, unchanged) + `worker.py` (StreamingPull) + rewritten `deploy/deploy_state_writer.sh` (worker pool + pull sub, push-auth IAM dropped). `main.py` tombstoned; `seed_test_state.py` now Firestore-direct only. `spec/state_writer_worker_pool.md` §built. NB: verify `gcloud run worker-pools deploy` flags against your gcloud |
| 9 | **`frame_tools` + `scorer` re-aim** | ✅ done (verified offline) | field-wide + selected-car boost; `get_field_state(selected_car)` + focus block; `shared/scorer.py` re-aimed (event-significance constants + `SELECTED_CAR_BOOST`). Resolutions + learnings in `spec/frame_tools_scorer_reaim.md` §5. Fed #4 |
| 10 | **Doc suite & run of show** | last | Student Guide / Run of Show / Demo / How It Works, mirroring Ch2 |
| 11 | **BQML / data-science** | stretch | segmentation / recommender |
| 12 | **`architecture.svg` rebuild** | 🔖 backlog — do as a LAST step | Current `docs/architecture.svg` is the stale Ch2 diagram (single agent, push state writer, A–F ladder). Rebuild for the Race-Day Companion (3 agents, worker-pool pull, fan UI, CX). Build is settled + plan ready: `spec/architecture_svg_plan.md` |

---

## 8. Sequencing — order of the next conversations

**Done: the CX integration spike (#2)** — the one true blocker is retired; the wire is validated (CX OpenAPI tool → ADK on Cloud Run). #3 and #5 are now unblocked.

**Now in parallel** (the team-split payoff), Patrick is running one spin-off at a time:

- **Track A — the data/agent spine:** #3 `race_data_subagent` (build it per the spike's reference impl) → #5 `cx_concierge`, with **#6 Knowledge-Base & RAG running just ahead of / alongside #5** since it feeds the concierge's grounding. (Grounding is now a known must-do: the stub showed the CX LLM will hallucinate from training data unless instructed to answer only from the subagent.)
- **Track B — the live spine: ✅ #9 `frame_tools`/`scorer` re-aim + #4 `commentator` DONE** (verified offline; live runbook `deploy/RUNBOOK_commentator.md`). Remaining: #8 state-writer Worker Pool whenever convenient.
- **Track C — surface:** #7 frontend adaptation — now unblocked on the agent side: the commentator emits `{type:"radio", selected_car, ...}` and consumes `{type:"select"}` via `CommentatorLoop.set_selection()`; #7 wires `frontend/main.py` to it. #12 `architecture.svg` anytime.

**Last: #10 doc suite & run of show** — needs the build settled.

Suggested next move: **#7 frontend adaptation** (wire the given UI's car-select to the commentator loop and render `{type:"radio"}` deliveries) — both agent voices (Track A concierge, Track B commentator) now exist for it to consume. #8 state-writer Worker Pool can run in parallel.

---

## 9. Canonical direction — the Race-Day Companion (v2)

A second-screen fan companion over the Berlin 2024 replay. Built on the **Challenge 2
simulator and an adapted Challenge 2 UI**, it has three parts on one page:

1. **Interactive track map + car list (the surface).** A map of the Tempelhof circuit with
   all cars on it, and a car list down the left. Click a car → it's highlighted on the map and
   a **stats panel** shows that car's live numbers (speed, power/energy, position, gap, Attack
   Mode). Adapted from the Ch2 pit-wall UI.

2. **The AI Commentator (live / push).** A **broadcaster** that gives a *running story of the
   whole field* in third-person — "out of Turn 2, car 5 is through on car 6" — not a
   first-person engineer to one driver (the key separation from Ch2). When the fan **selects a
   car**, the commentary **narrows focus** to that car and its battle with whoever's next to it.
   Spoken aloud via TTS. Reuses the Ch2 sim, trigger/scorer, agent chassis, and TTS; the *new*
   parts are the field-wide POV, the broadcast persona, and the selection-aware focus.

3. **The Concierge Chat (pull) — CX as orchestrator.** A **CX / Conversational Agents** bot
   embedded on the page, acting as an **orchestrator** over subagents/tools:
   - **RAG data stores** for **profiles** (teams/drivers) and **rules** questions — grounded on
     curated profiles + Google Search.
   - A **race-stats subagent** (ADK on the Agent runtime / Agent Engine, called by CX) that
     answers race and statistics questions from **BigQuery** — and is **time-honest** like Ch2
     (only sees up to the replay's current moment; no looking into the future).
   - **[CORE]** a live path so the bot can also answer *now* questions ("how's car 13 right
     now?") off the same Firestore "now" the commentator uses — the wire that makes this one
     companion, two voices, rather than a chatbot bolted on.

**Personalization = the selected car.** No fan-profile/CRM, no segmentation in the core
(parked as optional flavor). This also dissolves most of the §5 data gap: CX grounds on Google
Search instead of a bio/rules corpus we'd have to author.

### Teaching spine (v2)
> **"Two voices over one race — a live commentator that follows what you're watching, and an
> ask-anything concierge that's grounded enough to trust."**

New, non-Ch2 lessons: (a) **selection-aware generation** (output re-aims on user-chosen
context); (b) **grounding a CX agent** (Search + profiles, honest answers); (c) **composing two
engines** — a custom live agent + a managed CX bot — on one product surface.

### Reuse vs new (v2)
- **Reuse (heavy):** simulator → Pub/Sub → Firestore "now"; the pit-wall UI as a base; the
  trigger/scorer pattern; the ADK agent chassis; TTS; `setup/`+`deploy/` skeleton.
- **New build:** the interactive map + car-select + live stats panel (frontend); the broadcast
  persona + selection-aware tailoring (agent); the CX bot + grounding + the optional live webhook.

### Open tension to manage
The commentator is architecturally close to Ch2's race engineer. **Treat reuse as a feature**
and make sure the graded *new* learning lives in the UI interactivity, the CX build, the persona,
and the two-engine composition — not in re-teaching the scorer. Also confirm there's enough
hands-on **developer** work given the sim/UI are given and CX is low-code (the webhook/function
tool is the main lever here).

### Candidate tier ladder (v2, ~75 min — replaces §4)
- **A — Stand up the commentator (~10–15).** ADK agent, broadcast prompt; ungrounded → invents
  stats. (Same A-lesson: ungrounded = a podcast.)
- **B — Call the real race (~15–20).** Wire the live frame tools (Firestore "now") so it
  commentates actual sim events. (Reuses Ch2 frame tools.)
- **C — Selection-aware + the stats panel (~20).** Commentary re-aims on the clicked car; build
  the car-select → live stats panel. **The distinctive beat.**
- **D — Broadcast persona, out loud (~15).** Voice + TTS; it sounds like a real commentator.
- **E — The Concierge Chat (~20).** Stand up the CX bot, ground it (Google Search + team/driver
  profiles), embed it on the page.
- **F — Stretch.** CX webhook into live state (chat answers live questions); BQML; richer
  selection logic; a second persona.

### Decisions still open (v2)
> **Superseded — now reconciled in the §6 Decision register** (post-architecture). Kept for
> history: most of these are resolved (commentator = ADK; live wire = core via the subagent;
> TTS = yes; UI = given). Live ones moved to §6: RAG depth (#2/#6).
1. **Commentator engine** — assume ADK (consistent with Ch2, max reuse) unless we want a
   contrast. _Leaning ADK._
2. **Live webhook for the CX bot** — core tier or Tier F stretch? (Drives how unified the two
   surfaces feel, and how much dev meat there is.)
3. **Team/driver profiles for CX grounding** — author a small curated set, or rely on Google
   Search alone? How much depth.
4. **TTS confirmed** for the commentator? (Assumed yes — it's the wow.)
5. **How much UI work is student vs given** — the map + car-select is the biggest frontend lift;
   decide what's scaffolded vs built.

### Architecture — locked decisions (this session)
- **Front end is GIVEN.** Students build the **backend agents**; we hand them the UI (track map,
  car list, click-to-select, stats panel). The Ch2 pit-wall UI is the base but **will need real
  tweaking** for the map + selection model.
- **Three agents, clean team split** (a secondary but welcome benefit — Ch2 had no natural way to
  divide work): (1) the **live commentator** (ADK), (2) the **CX orchestrator** + its RAG data
  stores, (3) the **race-stats subagent** (ADK/BQ, time-honest) that CX calls. A couple of people
  can own the CX agent while others own the commentator and the stats subagent.
- **Keep from Ch2:** setup scripts **1–6** and the data layer they build; the simulator; the
  Pub/Sub → Firestore pipeline; BigQuery + the curated toolbox tools; TTS; the trigger/scorer
  *pattern*.
- **Change:** convert the **state writer** (currently a FastAPI **push-subscription** Cloud Run
  service, `state_writer/`) into a **Cloud Run Worker Pool** doing Pub/Sub **pull** — what worker
  pools are designed for. Safe because the writer is already idempotent (deterministic event IDs).
- **Re-aim (not just reuse):** `frame_tools` and `scorer` are written from car #13's "our car"
  POV — rework them to a **field-wide** broadcaster view, **boosted toward the selected car**.
- **Leave behind:** the `starter/` agent folder — Ch1 gets a **new starter**. Examine the
  existing solution agent + toolbox tools first to see what translates (the curated BQ tools look
  like a near-direct fit for the stats subagent).
- **Rebuild** `docs/architecture.svg` for the new design (some pieces unchanged).
- **CX talks to ONE race-data subagent, not Firestore directly.** That subagent owns both
  worlds (Firestore "now" + BigQuery "then", time-honest), keeping CX a pure orchestrator. CX
  reaches it via a native tool (**Agent as a tool** / **MCP** / **OpenAPI** — to be spiked;
  A2A+Agent-Registry is an experimental 4th option). CX also uses **Data store / File search**
  (profiles, rules) + **Google Search** grounding. Details + verified tool surface in
  `ARCHITECTURE_BRIEF.md`.

### Data-scope note (correction)
BigQuery isn't limited to this race: it holds **10 seasons of career + race results**
(`career_driver`, `career_race`). So the stats subagent can answer historical/career questions,
not just Berlin R10 — worth deciding how far we let it range.

### Architecture conversation — DONE (2026-06-19)
The architecture spin-off ran and **locked the target architecture + repo**. The build now
lives in `formula-e-fan-concierge/` (this repo): a clean skeleton vendoring the kept Ch2 pieces,
with three parallel sub-packages (`commentator`, `cx_concierge`, `race_data_subagent`) in
`starter/` and `solution/`. Key resolutions: CX→subagent over an **MCP tool** (async, Service
Agent ID Token); subagent owns Firestore "now" + BigQuery "then" **time-honest** over **R10 +
full career**, bounded to the current moment; state writer → **Cloud Run Worker Pool (pull)**;
frame_tools + scorer **re-aimed** field-wide with a selected-car boost. Full detail in
`ARCHITECTURE_BRIEF.md` ("Resolved this session") and `spec/` (`architecture.md`,
`cx_integration_spike.md`, `state_writer_worker_pool.md`, `frame_tools_scorer_reaim.md`,
`architecture_svg_plan.md`). Remaining v2 open items (#6 RAG backend, the live-wire tier
placement) move to their own spin-off conversations per §7.
