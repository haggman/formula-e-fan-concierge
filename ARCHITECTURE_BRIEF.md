# Architecture & repo skeleton — spin-off brief

_Seed for the architecture conversation. Self-contained: you can open a fresh chat, point it
at this file, and start. Full context lives in [`PLAN.md`](PLAN.md) §9 (the canonical concept)._

**Goal of that conversation:** lock the target architecture for Challenge 1 (the **Race-Day
Companion**) and lay out the new repo — exactly what we fork from `../formula-e-race-engineer/`,
what we change, and what we build fresh.

---

## ✅ Resolved this session (2026-06-19) — architecture LOCKED

The architecture conversation ran. Outcomes (full detail in `spec/`):

- **Repo layout (#4):** clean skeleton `formula-e-fan-concierge/` (new git repo, no Ch2
  history) **vendoring** the kept Ch2 pieces. **Three parallel sub-packages** in `starter/` and
  `solution/`: **`commentator`** (ADK), **`cx_concierge`** (CX low-code), **`race_data_subagent`**
  (ADK). Skeleton is scaffolded; see `README.md` and `spec/architecture.md`.
- **CX → subagent (#1) — VALIDATED LIVE 2026-06-19 (spike done):** the subagent is an **ADK agent on Cloud Run that serves its own `POST /ask_race_data` OpenAPI endpoint** (via `get_fast_api_app()` — the agent *is* the service, no wrapper); CX reaches it with an **OpenAPI tool**, **Service Agent ID Token** auth (`run.invoker` on `service-{PROJECT_NUMBER}@gcp-sa-ces.iam.gserviceaccount.com`); ~7–9 s round trips run synchronously. Proven end to end in the CX simulator. _This overturns the earlier Agent-Engine + Registry idea I'd put here:_ **CX cannot consume Agent Registry / A2A** (no such tool type in the live CX menu — those are for an ADK code orchestrator or the Gemini Enterprise app), and **Agent Engine can't serve a custom OpenAPI path** (only the `reasoningEngines` API). Agent Engine deploy (auto-registers in Agent Registry) + an A2A door (`to_a2a`, ~1 line) are kept as an **optional showcase tier**, off the critical path. Ref impl `spike/cx_openapi_spike/`; full writeup `spec/cx_integration_spike.md`.
- **Time-honesty (#2):** reuse the Ch2 clock bridge; subagent reads Firestore "now" first, then
  bounds every BigQuery call with `race_wall_time_ns`. Data range = **R10 + full 10-season
  career**, all bounded to the current moment (Patrick: all historical data fair game, up to now).
- **State writer (#5):** convert to a **Cloud Run Worker Pool (Pub/Sub pull)** →
  `spec/state_writer_worker_pool.md`.
- **frame_tools + scorer re-aim / selected-car path (#3):** field-wide + selected-car boost;
  selection arrives over the websocket → `spec/frame_tools_scorer_reaim.md`.
- **Stats data range (#7):** R10 + career (above).
- **Team split → ladder (#8):** parallel by package, each with its own mini-ladder →
  `spec/architecture.md`.
- **architecture.svg:** rebuild plan → `spec/architecture_svg_plan.md`.

Still open / deferred: **#2b** (Integration Connector → Firestore, only for the direct-connector
contrast/stretch), **#6** (RAG backend — leans Vertex AI Search; owned by the Knowledge-Base
conversation), and the Worker-Pool `gcloud` verb confirmation at build time.

---

## The product in one paragraph

A second-screen fan companion over the Berlin 2024 (R10) replay. A **given** front end shows an
interactive track map + car list; click a car to highlight it and see live stats. A **live
commentator agent** narrates the whole field broadcast-style and narrows focus to the selected
car, spoken aloud. A **CX (Conversational Agents) orchestrator** answers questions — grounded
profiles/rules via RAG + Google Search, plus a **race-stats subagent** over BigQuery (time-honest)
and a live path into Firestore "now." Students build the **backend agents**; the UI is given.

## Locked decisions (from planning, do not relitigate)

- Front end is **given**; students build the **three backend agents**.
- Three agents = natural team split: **commentator** (ADK) · **CX orchestrator** + RAG data
  stores · **race-stats subagent** (ADK/BQ, time-honest, called by CX).
- The CX↔live wire ("how's car 13 right now?") is **core**, not a stretch.
- Personalization = **selected car** (no fan CRM/segmentation in core).
- Commentator is **spoken** (reuse Ch2 TTS).
- Build on the Ch2 chassis; reuse heavily (details below).

## Reuse inventory (what's actually in `../formula-e-race-engineer/`)

**Keep ~as-is:**
- `setup/` scripts **1–6** (`1_enable_apis` … `6_deploy_simulator`) + the data layer they build.
- `simulator/` — the race replayer (Cloud Run) → Pub/Sub.
- BigQuery `fe_race10` (this race) **+ 10 seasons career/results** (`career_driver`, `career_race`).
- `toolbox/tools.yaml` — 14 curated BQ tools; the race ones map near-directly onto the stats
  subagent: `get_driver_info, get_lap_history, get_top_speed_history, get_energy_curve,
  get_recent_race_control, get_am_activations, get_am_armings, get_overtakes_involving,
  get_driver_career_stats, get_field_position_at_lap, get_lap_time_windows` (+ discovery +
  `execute_sql_bq` escape hatch).
- `frontend/tts.py` (and `stt.py` if we keep voice input); the websocket `radio`-message pattern.

**Change:**
- **State writer** (`state_writer/main.py`, setup step 5) — today a **FastAPI push-subscription**
  Cloud Run service (decodes Pub/Sub push → writes `RaceState` + events to Firestore, idempotent
  via deterministic IDs). **Convert to a Cloud Run Worker Pool** doing Pub/Sub **pull**. Safe
  because writes are idempotent. → revise setup step 5 + its deploy script.
- **`frame_tools.py`** (`get_current_state, get_recent_events, get_events_in_range,
  get_field_am_status`) — currently car-#13 "our car" POV. Re-aim to **field-wide** + a
  selected-car parameter.
- **`shared/scorer.py`** — weights are "us"-centric (`SCORE_WE_GOT_PASSED`, `SCORE_OUR_AM_*`).
  Re-aim to field-wide events with a **boost toward the selected car**.
- **`frontend/`** UI — leverage as the base, but real tweaking for the map + selection model +
  stats panel + the CX widget. (`frontend/engineer_loop.py` is the poll→score→fire→broadcast loop
  — becomes the commentator loop.)
- `docs/architecture.svg` — rebuild for the new design (some pieces unchanged).

**Leave behind / replace:**
- `starter/race_engineer/` — Ch1 gets a **new starter**. (Examine `solution/race_engineer/`
  — `agent.py`, `config.py`, `prompts.py`, `snapshot.py` — for what translates.)

## Target architecture (LOCKED — canonical version now in `spec/architecture.md`)

> The diagram below is the original sketch. The **locked** architecture, component-status table,
> and team→tier mapping now live in **`spec/architecture.md`**; rebuild plan for the SVG in
> **`spec/architecture_svg_plan.md`**.

```
[simulator · Cloud Run] → Pub/Sub → [State Writer · Worker Pool (pull)] → Firestore "now"
                                                                              │
   ┌──────────────────────────────────────────────────────────────────────┘
   ▼
[Commentator agent · ADK] ──(field-wide + selected car)──► websocket ─► [GIVEN Fan UI:
   └─ frame_tools (field POV) + scorer (field, selected-boost) + TTS              map · car list ·
                                                                                  stats panel · CX chat]
[CX orchestrator · Conversational Agents] ──► RAG data stores (profiles, rules) + Google Search
        ├──► race-data subagent · ADK on Cloud Run (OpenAPI) ──► toolbox ──► BigQuery (time-honest)
        └──► live lookup ──► Firestore "now"   (the CORE CX↔live wire)
```

## CX integration — verified tool surface & recommended design

Per the current CX / Conversational Agents **Tools** docs (page updated 2026-05-05), an
Agent Studio agent can use these tool types (verbatim names): **Agent as a tool** ("reuse
capabilities of agents without handing off to another agent"), **MCP tools** ("connect to an
MCP server"), **Data store tools** + **File search tools** (RAG over website/uploaded data /
knowledge base), **Google Search tools** (grounding), **Integration Connector tools** (uses
configured Connections), **OpenAPI tools**, **Python code tools**, **Client function tools**,
**System tools**, **Widget tools**, plus Salesforce/ServiceNow.

What this means for us:
- **CX → race-data subagent:** three candidate wires, in order of "documented & simple":
  (1) **Agent as a tool**, (2) **MCP tools**, (3) **OpenAPI**. _(Superseded — the live spike on 2026-06-19 settled it: the validated wire is the **CX OpenAPI tool → ADK agent on Cloud Run** (`POST /ask_race_data`). Both "native" candidates were disproven — CX can't consume Agent Registry/A2A, and Agent Engine can't serve a custom OpenAPI path. See the "Resolved this session" block at the top and `spec/cx_integration_spike.md`. This bullet is kept only as a record of the earlier reasoning.)_
- **Profiles + rules:** **Data store / File search tools** (RAG) + **Google Search tool**.
- **Recommended data design (resolves the "CX → Firestore directly?" question):** put an
  **intelligent race-data subagent behind CX** that owns **both** worlds — Firestore "now" +
  BigQuery "then" (time-honest) — instead of wiring CX straight to Firestore. Rationale: the
  valuable questions ("how's my driver done over recent seasons?") are **BigQuery**, not
  Firestore; one data agent = one clean tool for CX = CX stays a pure orchestrator. A direct
  **Integration Connector to Firestore** for simple "now" lookups is a possible
  contrast/stretch (pending confirming connectors support Firestore on the `/ps/tool/connector`
  sub-page) — not the backbone.
- **Async execution:** CX tools have a sync (<~5 s) vs async (5–60 s) execution mode — relevant
  if a subagent call is slow; note it when wiring.

> All of the above is the working hypothesis; the integration must be **validated by a spike**
> when we build (Patrick's call, and correct — this is the riskiest unknown).

## Open questions for the architecture conversation

1. **How CX calls the subagent (the spike)** — compare the three native wires (**Agent as a
   tool** vs **MCP tool** vs **OpenAPI**) and Patrick's Agent-Registry+MCP+A2A route; pick one.
   Confirm what kind of agent "Agent as a tool" accepts (Agent Engine / ADK?). See the CX
   integration section above.
2. **Time-honesty mechanism for the race-data subagent** — reuse Ch2's `race_wall_time_ns` clock
   bridge? How does the subagent learn the replay's current moment (read Firestore "now" first,
   then bound BigQuery queries)? Note the subagent owns both worlds, so it can self-bound.
2b. **Does the Integration Connector support Firestore/BigQuery?** — check `/ps/tool/connector`;
   only matters if we want the direct-connector contrast/stretch.
3. **Selected-car signal path** — how the UI selection reaches the commentator (websocket msg?)
   and the CX/live lookup.
4. **Repo layout** — fork the Ch2 repo into `formula-e-fan-concierge/` (new git repo) vs a clean
   skeleton that vendors the kept pieces. Naming of the new starter/solution packages.
5. **Worker Pool specifics** — pull subscription config, scaling, local-dev story (push was
   trivially curl-able; pull needs an emulator or a deployed sub).
6. **RAG backend** — Vertex AI Search data store vs other; how profiles get authored/loaded.
7. **Data range for stats** — limit the subagent to R10, or allow the 10-season career/results?
8. **Tier mapping → team split** — does the A–F ladder still work when 3 sub-teams build in
   parallel, or do we want a parallel (not purely sequential) build structure?

## First moves — DONE (see "Resolved this session" at the top)

- ✅ Repo layout (#4) — clean skeleton scaffolded; three sub-packages.
- ✅ CX↔subagent integration (#1, #2) — MCP tool + spike defined.
- **Next:** run the CX spike (`spec/cx_integration_spike.md`), then the build conversations —
  Worker-Pool conversion, the field-wide re-aim, the three agents, RAG/grounding, the SVG
  rebuild — against the §7 work breakdown in `PLAN.md`.
