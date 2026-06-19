The **Architecture & infra reuse** spin-off (work item #1) is done. The Challenge 1 build now lives in `formula-e-fan-concierge/` and the architecture is **locked**. Please update PLAN.md's tracking and sequence the next spin-offs.

**What was resolved:**

- **Repo:** clean skeleton (new repo, no Ch2 history) vendoring the kept Ch2 pieces; three parallel sub-packages in `starter/` and `solution/` — `commentator` (ADK), `cx_concierge` (CX low-code), `race_data_subagent` (ADK). Skeleton scaffolded; code adaptation spec'd, not implemented.
- **CX→subagent:** MCP tool (StreamableHttp on Cloud Run, Service Agent ID Token, async). OpenAPI = fallback; Agent-as-a-tool rejected as backbone (reuses an agent inside the CX app, Preview); A2A/Agent-Registry deferred. Validated against current docs; a spike is defined.
- **Subagent** owns Firestore "now" + BigQuery "then", time-honest, over R10 + full 10-season career, bounded to the current moment.
- **State writer** → Cloud Run Worker Pool (Pub/Sub pull). **frame_tools + scorer** re-aimed field-wide with a selected-car boost (selection over the websocket).

**Source of truth:** `ARCHITECTURE_BRIEF.md` ("Resolved this session") and `spec/` (`architecture.md`, `cx_integration_spike.md`, `state_writer_worker_pool.md`, `frame_tools_scorer_reaim.md`, `architecture_svg_plan.md`).

**Still open / for sequencing:** run the **CX spike** (gates real subagent work); **#6 RAG backend** (Knowledge-Base & RAG conversation — leans Vertex AI Search; profiles + rules pack must be *authored*); confirm the `gcloud run worker-pools` deploy verb at build time; **#2b** Integration Connector→Firestore (only if we want the direct-connector contrast). Please reconcile §6–§7 with these outcomes and propose the order of the next conversations (suggested first: the CX spike, then the three parallel package builds, with Knowledge-Base/RAG feeding `cx_concierge`).
