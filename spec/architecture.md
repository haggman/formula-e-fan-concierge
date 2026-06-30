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
   │ CX        │  │  deployed to Cloud Run;           │   bound BQ by    │
   │ Concierge │──┤  reached via CX OpenAPI tool      │   race_wall_time │
   │ orchestr. │  │  tool: ask_race_data(question)    │   _ns from "now" │
   └─────┬─────┘   OpenAPI tool     └────────┬──────────┘                 │
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
| Trigger/scorer pattern | **Re-aimed ✅ built**: field-wide + selected-car boost | `shared/scorer.py` + `spec/frame_tools_scorer_reaim.md` §5 |
| Frame tools | **Re-aimed ✅ built**: `get_field_state(selected_car)` + focus block | `*/commentator/tools/frame_tools.py` |
| Commentator loop | **New ✅ built**: selection-aware fork of engineer_loop | `frontend/commentator_loop.py` |
| Fan UI | **Reworked ✅ (companion page)**: field-wide list + click-to-select + selected-car stats panel + spoken commentary feed; selection over websocket. Map + CX widget embed = follow-ons | `frontend/main.py`, `frontend/static/index.html` |
| Commentator agent | **New ✅ built** (ADK), forked from race engineer; verified offline, live runbook ready | `*/commentator/` + `deploy/RUNBOOK_commentator.md` |
| Race-data subagent | **New** (ADK), owns now+then, deployed to **Cloud Run** (CX OpenAPI tool) | `*/race_data_subagent/` |
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

The skeleton vendored Ch2 infra **as-is**, referencing the old `race_engineer` package via the
`AGENT_PACKAGE` seam. The commentator build (#9 + #4, 2026-06-29) re-pointed and adapted the
pieces it owns; the rest stay for #7/#8.

**Done in the commentator build:**
- `shared/scorer.py` — re-aimed field-wide + selected-car boost (was Ch2 car-13 weights).
- `shared/agent_pkg.py` seam default → `solution.commentator`; `activate.sh` default →
  `starter.commentator` (the `race_engineer` package is left behind / absent).
- `frontend/commentator_loop.py` — new, the selection-aware fork of `engineer_loop.py`.
- `scripts/test_frame_tools.py` — retargeted to the field-wide tools; new
  `scripts/local_commentator.py` (live harness) and `scripts/verify_commentator_offline.py`
  (no-GCP check).

**Done in the #7 frontend pass:** `frontend/main.py` rewired — `EngineerLoop` →
`CommentatorLoop`, `OUR_CAR_NUMBER` dropped, reads `shared.state_client`, field-wide
`ui_state`, and the inbound `{type:"select"}` handler → `set_selection()`.
`frontend/static/index.html` reworked into the companion page (click-to-select list +
selected-car stats panel + spoken commentary feed). `frontend/engineer_loop.py` is now
superseded by `commentator_loop.py` and can be deleted.

**Still to rewire (follow-ons / #8 deploy):** the CX chat-widget embed (placeholder marked in
`index.html`) and the track map are the #7 follow-on passes; `frontend/agent_client.py` `APP_NAME`
is cosmetic; `setup/8_deploy_cloud.sh` rename + `deploy/build_engine_app.py` /
`deploy/deploy_frontend.sh` are #8 (Cloud Run deploy — runs locally via uvicorn today); the
leftover Ch2 dev scripts (`local_test.py`, `agent_chat.py`, `stage_probe.py`) still name
`race_engineer` and are superseded by `scripts/local_commentator.py`.
