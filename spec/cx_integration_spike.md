# CX ↔ race-data subagent — integration decision & validation spike

Resolves open questions **#1** (how CX calls the subagent) and **#2** (time-honesty). This was the riskiest unknown; the decision below is grounded in current Google Cloud docs and **must be confirmed by the spike** before the build.

> **Revised 2026-06-19 (Patrick's review).** The primary transport was changed from a hand-rolled **MCP server on Cloud Run** to the native **Agent Engine runtime + Agent Registry** path. Rationale: ADK agents now deploy to the Agent Engine runtime with a single `adk deploy`, and **Agent Registry** is "a centralized catalog for discovering, tracking, and managing all agents, tools, and **MCP servers** across the organization." Hand-rolling an MCP server on raw Cloud Run bypasses the very platform this hackathon is meant to showcase. The Cloud Run MCP server is retained only as a **fallback** if the Agent-Engine→CX wire isn't ready (parts are Preview).

## Runtime decision: the subagent runs in **Agent Engine**

Build the race-data subagent in **ADK**; deploy it to the **Agent Engine runtime** via `adk deploy`. This is the managed home for ADK agents (single-command deploy; Agent Engine sessions + memory bank are GA as of 2026), and it's what Agent Registry catalogs. The agent's *brain* lives in Agent Engine regardless of which CX-facing wire we end up using.

## Connection decision (to validate): CX → Agent Registry → Agent-Engine agent (via MCP)

Primary target: the CX orchestrator reaches the subagent as a tool **discovered through Agent Registry**, pointing at the **Agent-Engine-hosted** agent over **MCP**. CX Agent Studio agents are ADK under the hood, so this is an on-platform ADK↔ADK connection — the most native design and the best story for showing off Google's agent stack.

```
CX Agent Studio (orchestrator, ADK under the hood)
   │  tool discovered via Agent Registry → MCP
   ▼
race-data subagent  —  deployed to Agent Engine runtime (adk deploy)
   ├─ MCP Toolbox (BigQuery: R10 + 10-season career)   [reused from Ch2]
   └─ now_tools (Firestore "now", field-wide)           [new, small]
```

**The uncertainty the spike must retire:** whether an Agent-Engine-deployed agent is exposed to CX's MCP tool — directly or through the registry — *today*. The registry cataloging "MCP servers" strongly implies this wiring exists, but parts are Preview/Pre-GA. If it isn't ready, we fall back (below) without losing the Agent Engine runtime.

### Options (re-ranked after review)

| Option | Verdict | Reasoning |
|---|---|---|
| **Agent Engine + Agent Registry + CX (MCP)** ✅ | **Primary** | Native, on-platform, single-command deploy; registry is purpose-built to catalog and surface agents/MCP servers to consumers like CX. Showcases the Google agent stack. Preview risk on the exact CX-facing wire → that's what the spike proves. |
| **Thin MCP server on Cloud Run** ◻️ | **Fallback (documented-today)** | CX's MCP tool connects to a StreamableHttp MCP server on Cloud Run (`/mcp`, Service Agent ID Token + `run.invoker`); docs page updated 2026-06-03, no Preview banner — known to work. The Cloud Run service can be a **thin MCP facade that calls the Agent-Engine agent**, so the agent brain still lives in Agent Engine. Use if the registry/Agent-Engine→CX path isn't ready in time. |
| **OpenAPI tool** ◻️ | **Second fallback** | Plain HTTPS + OpenAPI spec, same auth options. Loses MCP symmetry with Ch2; a spec to maintain. |
| **Agent as a tool** ⚠️ | **Not the backbone** | Reuses an agent *inside the same CX app* (no external endpoint) → would force authoring the subagent in CX low-code, killing the ADK subagent and the team split. Preview. Its sync/async guidance is still useful. |

### Verified facts (current docs, pulled 2026-06-19)

- **ADK → Agent Engine:** `adk deploy` deploys an ADK agent to the Agent Engine (AE) runtime in one command; AE sessions + memory bank are GA; container-image deploys are supported for build control.
- **Agent Registry:** "a centralized catalog for discovering, tracking, and managing all agents, tools, and MCP servers across the organization"; admins curate approved tools via a Cloud API Registry; ADK adds an `ApiRegistry` object to consume registry-managed tools.
- **CX MCP tools:** connect to an existing MCP server; **StreamableHttp only (no SSE)**; URL ends `/mcp`; host on Cloud Run or Compute Engine; build with the MCP SDK or **FastMCP**; prebuilt Google Cloud MCP servers allowed. For Cloud Run, recommended auth is a **Service Agent ID Token** using `service-{PROJECT_NUMBER}@gcp-sa-ces.iam.gserviceaccount.com` with **`roles/run.invoker`**. (Updated 2026-06-03.)
- **CX = Conversational Agents console:** the unified console merging Dialogflow CX + Vertex AI Agent Builder; CX Agent Studio is its minimal-code builder with out-of-the-box connectors + MCP support.

### Execution mode

The subagent does multiple LLM + tool calls per question, so a round trip can exceed the ~5 s **sync** ceiling. Configure the CX tool for **async / long-running** (5–60 s) execution. If latency is consistently high, return an immediate ack and summarize on completion (the async-tool instruction pattern from the docs).

## Time-honesty mechanism (open #2 — resolved)

Reuse Ch2's clock bridge verbatim: `RACE_START_EPOCH_NS` + `race_time_to_wall_ns()` (green flag 2024-05-12T13:04:05.726Z). The subagent **self-bounds** because it owns both worlds:

1. On each question, call a `now_tool` first → current `race_time_s` + `race_wall_time_ns`.
2. Pass `race_wall_time_ns` as `through_time_ns` to **every** BigQuery Toolbox call.
3. Prompt forbids reporting anything after the current moment (no spoilers / final results mid-replay).

**Data range (confirmed with Patrick):** all historical/career data is fair game — R10 **and** the 10-season career/results — but bounded to "up to this moment." Career data predates the current moment, so the single `through_time_ns` bound covers it; inside R10 the future stays hidden. Mechanism enforces it; prompt reinforces it. (The Ch2 `AgentEvent` model already strips the replay machine's wall clock to stop a 2026 timestamp leaking in as `through_time_ns` — keep that guard.)

## The spike (do this before building the real subagent)

**Goal:** prove the **native path** end to end with a *stub* subagent — and if it's blocked by Preview gaps, prove the Cloud Run fallback — so the integration risk is retired before real agent work.

**Path A — native (try first):**

1. **Minimal ADK agent.** One tool `ask_race_data(question: str) -> str` that (a) reads Firestore "now" and computes `race_wall_time_ns`, (b) returns a canned answer echoing that value. No BQ yet.
2. **`adk deploy` to Agent Engine.** Confirm the agent runs in the AE runtime.
3. **Register in Agent Registry.** Confirm the agent (and its MCP surface) appears in the catalog.
4. **Wire from CX:** add the registry/MCP tool in CX Agent Studio pointing at the Agent-Engine agent; confirm tool discovery + auth.
5. **Ask in the CX simulator:** "how's car 13 right now?" → confirm CX calls the tool and renders the answer with the live moment.
6. **Async check:** add a ~10 s delay → confirm long-running execution behaves; tune the mode.
7. **Negative (time-honesty) check:** ask a "who wins?" / future question → confirm the bound + prompt refuse to leak.

**Path B — fallback (only if A is blocked):** deploy a thin StreamableHttp **MCP server on Cloud Run** (FastMCP, `/mcp`) that calls the Agent-Engine agent (or embeds the ADK agent directly); `--no-allow-unauthenticated`; grant `roles/run.invoker` to `service-{PROJECT_NUMBER}@gcp-sa-ces.iam.gserviceaccount.com`; `curl` the `/mcp` endpoint with an ID token to confirm tool list + execution; add the CX **MCP tool** at `https://<svc>/mcp` with Service Agent ID Token auth; then run steps 5–7 above.

**Success criteria:** a CX→subagent round trip works (via Path A if possible, else Path B); >5 s handled via async; the live moment is read correctly; no future leak. **Record which path succeeded** — it determines the real `race_data_subagent` build and deploy story.

## Open sub-question (cheap, parallelizable)

**#2b — Integration Connector → Firestore/BigQuery?** Only matters if we want the direct-connector contrast/stretch (CX → Firestore for trivial "now" lookups, bypassing the subagent). Check the `/ps/tool/connector` sub-page for a Firestore connector. Not the backbone — the subagent owns "now."
