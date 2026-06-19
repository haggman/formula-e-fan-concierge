# Target architecture — The Race-Day Companion (LOCKED, this session)

The canonical architecture for Challenge 1. Supersedes the ASCII sketch in
`ARCHITECTURE_BRIEF.md`; the brief now points here.

## System diagram

```
                         ┌──────────────────────────── GIVEN FAN UI (one page) ───────────────────────────┐
                         │  track map · car list · click-to-select · live stats panel · CX chat widget     │
                         └───────▲───────────────────────▲───────────────────────────────────▲────────────┘
                                 │ websocket             │ websocket                          │ embedded
                                 │ {radio} out           │ {select} in                        │ chat
   DATA PLANE (kept)             │                       │                                    │
   ┌───────────────┐   Pub/Sub   ┌──────────────────┐   │   ┌──────────────────────────┐     │
   │ Simulator     │── fe-tele ─►│ State Writer      │   │   │ Commentator · ADK        │     │
   │ (Cloud Run)   │   metry     │ WORKER POOL (pull)│   └──►│  field-wide + selected   │     │
   └───────────────┘             │  → Firestore "now"│       │  frame_tools + scorer    │     │
                                 └─────────┬─────────┘       │  (selected-car boost)+TTS│     │
                                           │ race_states /   └────────────┬─────────────┘     │
                                           │ race_events                  │ reads "now"       │
                                           ▼                              ▼                   │
                                 ┌─────────────────────────── Firestore "now" ───────────────┘
                                           ▲                              ▲
                                           │ reads "now"                  │
                  ┌────────────────────────┴──────────┐                  │
                  │ Race-Data Subagent · ADK          │                  │
   CX (low-code)  │  now_tools (Firestore) +          │                  │
   ┌───────────┐  │  ToolboxToolset (BigQuery)        │   time-honest:   │
   │ CX        │  │  deployed to Agent Engine;        │   bound BQ by    │
   │ Concierge │──┤  reached via Agent Registry/MCP   │   race_wall_time │
   │ orchestr. │  │  tool: ask_race_data(question)    │   _ns from "now" │
   └─────┬─────┘   registry/MCP     └────────┬──────────┘                 │
         │ Data store/File search  ▼                                     │
         │ (profiles, rules)   ┌──────────────┐   ┌──────────────────────┴───┐
         │ + Google Search     │ MCP Toolbox  │──►│ BigQuery: R10 + 10-season │
         └─────────────────────│ (Cloud Run)  │   │ career/results (time-honest)
                               └──────────────┘   └───────────────────────────┘
```

## Component status

| Component | Status | Where |
|---|---|---|
| Simulator → Pub/Sub | **Kept** as-is | `simulator/` |
| State Writer | **Changed**: push service → **Worker Pool (pull)** | `state_writer/` + `spec/state_writer_worker_pool.md` |
| Firestore "now" pipeline | **Kept** | (data plane) |
| MCP Toolbox (14 BQ tools) | **Kept** | `toolbox/tools.yaml` |
| BigQuery (R10 + 10-season career) | **Kept**; subagent may range over all, time-honest | — |
| TTS | **Kept** | `frontend/tts.py` |
| Trigger/scorer pattern | **Re-aimed**: field-wide + selected-car boost | `shared/scorer.py` + `spec/frame_tools_scorer_reaim.md` |
| Frame tools | **Re-aimed**: field-wide + `selected_car` | `*/commentator/tools/frame_tools.py` |
| Fan UI | **Given**, reworked for map + selection + stats + CX widget | `frontend/` |
| Commentator agent | **New** (ADK), forked from race engineer | `*/commentator/` |
| Race-data subagent | **New** (ADK), owns now+then, deployed to **Agent Engine** | `*/race_data_subagent/` |
| CX concierge | **New** (CX low-code), MCP + RAG + Search | `*/cx_concierge/` |
| Starter race_engineer | **Left behind** | (not vendored) |
| architecture.svg | **Rebuild** | `docs/` + `spec/architecture_svg_plan.md` |

## Locked decisions (this session)

1. **Repo:** clean skeleton (`formula-e-fan-concierge/`) vendoring kept Ch2 pieces; new git
   repo (no Ch2 history). Three parallel sub-packages in `starter/` and `solution/`:
   `commentator`, `cx_concierge`, `race_data_subagent`.
2. **CX → subagent (RESOLVED 2026-06-19 by the spike, validated live):** subagent is an **ADK agent on Cloud Run serving its own `POST /ask_race_data` OpenAPI endpoint** (the agent is the service — no wrapper); CX reaches it via an **OpenAPI tool** with **Service Agent ID Token** auth (`run.invoker` on the `gcp-sa-ces` service agent). "CX via Agent Registry / A2A" is **not consumable by CX** today, and **Agent Engine can't serve a custom OpenAPI path** — both ruled out by the spike. MCP-on-Cloud-Run also works but isn't chosen. Agent Engine deploy (auto-registers in Agent Registry) + an A2A door are an **optional showcase tier**, off the critical path. See `spec/cx_integration_spike.md`.
3. **Subagent owns both worlds**, time-honest via the reused clock bridge; data range = R10 +
   full 10-season career, all bounded to the current moment.
4. **State writer → Cloud Run Worker Pool (pull)**; safe via existing idempotency. See spec.
5. **frame_tools + scorer re-aimed** field-wide with selected-car boost; selection arrives over
   the websocket. See spec.

## Team split → tier ladder

| Team | Owns | Tiers (v2 ladder) |
|---|---|---|
| Commentator | `*/commentator/`, the commentator loop, TTS | A (stand up) · B (live frame tools) · C (selection-aware + stats panel) · D (persona/TTS) |
| Race-data subagent | `*/race_data_subagent/`, MCP server | underpins CX tier E + the live wire; built in parallel |
| CX concierge | `*/cx_concierge/`, grounding, MCP wire | E (stand up + ground) · F (live wire via the subagent) |

The data plane (simulator → worker pool → Firestore) and the given UI are shared infrastructure
all three depend on; stand them up first (`setup/all.sh`). Build is **parallel**, not the strict
A–F sequence of Ch2 (open #8 resolved: parallel by package, each with its own mini-ladder).

## Known vendored-infra rewires (build-time, not done this session)

The skeleton vendors Ch2 infra **as-is**; these still reference the old `solution.race_engineer`
package via the `AGENT_PACKAGE` seam and get re-pointed to `commentator` during the build:
`frontend/engineer_loop.py` (→ `commentator_loop.py`), `frontend/agent_client.py`,
`shared/agent_pkg.py` (the seam default), `activate.sh`, `setup/7_deploy_cloud.sh`,
`deploy/build_engine_app.py`, `deploy/deploy_frontend.sh`, and `scripts/*` (local_test,
agent_chat, stage_probe, test_frame_tools). `shared/scorer.py` keeps Ch2's car-13 weights until
the re-aim lands (`spec/frame_tools_scorer_reaim.md`). All intentional: this session locks the
architecture and lays out the repo; code adaptation is spec'd, not implemented.
