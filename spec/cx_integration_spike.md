# CX ↔ race-data subagent — integration decision & validation spike

Resolves open questions **#1** (how CX calls the subagent) and **#2** (time-honesty). This was the riskiest unknown; the spike ran live on 2026-06-19 and **retired it**. The decision below is now grounded in current Google Cloud docs **and** a working end-to-end test.

> **RESULT (2026-06-19, validated live).** The winning wire is **CX OpenAPI tool → an ADK agent deployed to Cloud Run that serves its own `POST /ask_race_data` endpoint**, authenticated with a **Service Agent ID Token** (`run.invoker` on the `gcp-sa-ces` service agent). Proven in the CX Agent Studio simulator: discovery, auth, a live-moment answer ("how's car 13 right now?" → race time 27:46 from Firestore "now"), and a refused future question ("who wins?"). The two paths the spec previously favored were **disproven as the wire**: (a) CX discovering the agent **via Agent Registry / over A2A** is **not supported by CX today** — the live CX "Create a tool" menu has **no A2A or Agent Registry tool type**; (b) **Agent Engine cannot serve a custom OpenAPI endpoint** — a deployed agent is reachable only through the fixed `reasoningEngines` API. The earlier "MCP server on Cloud Run" idea also works but adds the MCP mental model for no student payoff over plain OpenAPI. See the re-ranked options and evidence below.

## Runtime decision (validated): the subagent runs on **Cloud Run**, serving its own OpenAPI

Build the race-data subagent in **ADK**. For the CX wire it runs **on Cloud Run** and **is the service** — ADK's `get_fast_api_app()` returns a real FastAPI app, and we add a single clean operation `POST /ask_race_data {question} -> {answer}` (FastAPI also auto-serves `/openapi.json`). There is **no separate wrapper/facade**: the agent container is the OpenAPI endpoint CX calls. This was Patrick's explicit constraint ("if AE can't serve OpenAPI directly, deploy to Cloud Run and serve it ourselves — no thin wrapper layer"), and the docs forced it (next section).

**Agent Engine stays in the story as an optional showcase**, not the chat wire: the same ADK agent can be deployed to Agent Engine (where it **auto-registers in Agent Registry**) and can expose an **A2A** door (`to_a2a(root_agent)`, ~1 line, auto-serves an agent card). That's the "look how the platform discovers and governs agents" beat for a stretch tier — but CX does not consume it, so it never sits on the critical path.

## Connection decision (validated): CX **OpenAPI tool** → Cloud Run `/ask_race_data`

```
CX Agent Studio (orchestrator, low-code)
   │  OpenAPI tool (single operation: ask_race_data)
   │  auth: Service Agent ID Token  →  service-{PROJECT_NUMBER}@gcp-sa-ces.iam.gserviceaccount.com  (run.invoker)
   ▼
race-data subagent  —  ADK agent on Cloud Run, serves POST /ask_race_data
   ├─ now_tools (Firestore "now", field-wide)           [reads race_states/{race_id}]
   └─ MCP Toolbox (BigQuery: R10 + 10-season career)    [reused from Ch2; added in the real build]
```

Why OpenAPI and not the alternatives: it's GA, conceptually simple for a 3-hour student lab (REST + a schema), maps perfectly to CX's "one operation per OpenAPI tool" rule, and — when the Cloud Run service is in the **same project** as the CX agent — auth is the easy path (the Service-Agent-ID-Token option is purpose-built for invoking Cloud Run). A2A and MCP are both real but add moving parts and (for A2A/registry) aren't consumable by CX at all.

### Options (re-ranked after the spike)

| Option | Verdict | Reasoning (evidence-based) |
|---|---|---|
| **ADK agent on Cloud Run, served as an OpenAPI tool** ✅ | **WINNER (validated live)** | Simplest GA path; CX has a first-class OpenAPI tool; one-operation match; same-project Cloud Run auth is trivial; ADK `get_fast_api_app()` lets us add `POST /ask_race_data` directly. Proven end to end in the simulator 2026-06-19. |
| **MCP server on Cloud Run (CX MCP tool)** ◻️ | **Works, not chosen** | Same plumbing as OpenAPI (a Cloud Run service, Service Agent ID Token, `run.invoker`) but adds the MCP/StreamableHttp mental model. Keep only if Ch2 Toolbox symmetry is wanted. |
| **CX via Agent Registry / A2A (the "native" path)** ❌ | **Not supported by CX** | Agent Registry (Preview) does auto-register Agent-Engine agents and index A2A cards, but its documented consumers are an **ADK code orchestrator** and the **Gemini Enterprise app** — **not** CX Agent Studio. Confirmed in the live CX "Create a tool" menu: no A2A tool, no Agent Registry tool. The only "Agent" tool is in-app agent-as-a-tool. |
| **Agent Engine serving OpenAPI directly** ❌ | **Not possible** | A deployed Agent-Engine agent is reachable only via `LOCATION-aiplatform.googleapis.com/.../reasoningEngines/RESOURCE_ID` with the platform's own request/response shape — even a bring-your-own-container deploy gets no public custom path. So it can't present a clean `POST /ask_race_data` for CX. |
| **A2A / Agent Registry as a showcase** ✨ | **Optional stretch tier** | Deploy the same agent to Agent Engine (auto-registers) + expose A2A (`to_a2a`, ~1 line). Great teaching ("one brain, two doors") but off the critical path. |

### Verified facts (current docs + live console, 2026-06-19)

- **Agent Registry** (Preview; overview updated 2026-04-21): "a centralized, unified catalog … MCP servers, tools, and AI agents." **Automatic registration**: "Vertex AI Agent Engine: Agents deployed using the SDK are registered without additional configuration"; A2A agents have skills extracted from their Agent Card. Its **consumers** are an ADK code orchestrator (`AgentRegistry` client, `get_remote_a2a_agent`) and the Gemini Enterprise app — **not** CX Agent Studio.
- **Agent Engine invocation** ("Use an agent", updated 2026-04-27): external access only via `https://LOCATION-aiplatform.googleapis.com/.../reasoningEngines/RESOURCE_ID/api/...` (or `:query`/`:streamQuery`), OAuth access token + IAM. No public custom path; "Agent Runtime deployment only supports Python."
- **CX OpenAPI tool** (`.../ps/tool/open-api`, updated 2026-05-08): give an OpenAPI 3.0 schema; **one operation per tool**; auth options are **Service agent ID token** (ID token via `service-{PROJECT_NUMBER}@gcp-sa-ces.iam.gserviceaccount.com`; `run.invoker`/`cloudfunctions.invoker` for cross-project Cloud Run; same-project needs no extra IAM), Service Account auth (mints an access token), OAuth, API key. Sync ideal < 5s; async ideal 5–60s.
- **CX tool menu (seen live)**: Agent (in-app delegate), Client function, Cloud Storage, Confluence, Data store, File search, Google Maps (Preview MCP), Google Search, Integration connector, Jira, MCP server, OpenAPI, Python code, Salesforce, ServiceNow, SharePoint, Website. **No A2A / Agent Registry tool.**
- **ADK on Cloud Run**: `get_fast_api_app()` returns a FastAPI app (auto `/openapi.json`); you can add your own `@app.post("/ask_race_data")`. **A2A**: `to_a2a(root_agent)` (~1 line) auto-generates and serves an agent card; A2A is JSON-RPC + agent-card, **not** OpenAPI.
- **CX = Conversational Agents / CX Agent Studio** (Gemini Enterprise Agent Platform; formerly Dialogflow CX + Vertex AI Agent Builder).

### Execution mode (async)

The subagent does multiple LLM + tool calls, so a round trip can exceed the ~5s **sync** ideal; CES guidance puts async/long-running at ~5–60s. **Observed in the spike (LLM mode, validated 2026-06-19):** a simulator turn showed the `ask_race_data` **tool call taking 7.148s** (real model + live Firestore read), total turn 8.819s, and **CX handled it cleanly in the default synchronous configuration — no async setting, no timeout, no error.** So a genuine >5s *tool* round trip is tolerated as-is; the async/long-running setting is advisory headroom (helpful if latency climbs toward the ~60s range), not a hard requirement at ~7–9s. (Earlier "Request URL was unreachable – Internal Server Error" failures were **not** latency — they were a stub bug: a module-level session service with a fixed session id threw `AlreadyExistsError` on the 2nd+ request per warm instance. Fixed by a unique per-request session id. Lesson worth keeping for students: this is why "the tool test works but the agent call fails" — the test harness hits a cold first-request, the agent hits the warm instance.)

**Note (grounding, for the cx_concierge build):** with the *stub* returning only the live moment, the CX orchestrator LLM embellished its final reply with ungrounded facts (driver name, position) from its own training knowledge. The real subagent must return those as data and the CX instructions/grounding must forbid the orchestrator from inventing the rest.

## Time-honesty mechanism (open #2 — resolved & validated)

Reuse Ch2's clock bridge verbatim: `RACE_START_EPOCH_NS = 1_715_519_045_726_000_000` + `race_time_to_wall_ns()` (green flag 2024-05-12T13:04:05.726Z). The subagent **self-bounds** because it owns both worlds:

1. On each question, read Firestore "now" first → current `race_time_s` + `race_wall_time_ns`.
2. Pass `race_wall_time_ns` as `through_time_ns` to **every** BigQuery Toolbox call.
3. Prompt forbids reporting anything after the current moment (no spoilers / final results mid-replay).

**Validated live:** reading `race_states/{race_id}` gave a live `race_time_s` (e.g. 1551 → `race_wall_time_ns` 1715520596726000000; 27:46 in the simulator), and a "who wins?" question was refused ("I can only speak to the race as it stands right now"). The stub enforces the refusal with a keyword guard; the real subagent enforces it mechanically via the `through_time_ns` bound + prompt. (The Ch2 `AgentEvent` model already strips the replay machine's wall clock so a 2026 timestamp can't leak in as `through_time_ns` — keep that guard.)

**Data range (confirmed):** all historical/career data is fair game — R10 **and** the full 10-season career/results — but bounded to "up to this moment." Career data predates the current moment, so the single `through_time_ns` bound covers it; inside R10 the future stays hidden.

## What the spike validated (do this in the real build)

The spike artifacts live in `spike/cx_openapi_spike/` (stub agent `agent.py`/`now.py`, FastAPI service `app.py`, `Dockerfile`, `requirements.txt`, trimmed `openapi_ask_race_data.yaml`, plus `RUNBOOK.md` and `CX_WIRING.md`). The real `race_data_subagent` build follows the same shape:

1. **ADK agent** with `now_tools` (Firestore) + `ToolboxToolset` (BigQuery), time-honest prompt.
2. **Serve on Cloud Run** via `get_fast_api_app()` + a single `POST /ask_race_data` operation. The agent is the service.
3. **Deploy private** (`--no-allow-unauthenticated`); grant `roles/run.invoker` to `service-{PROJECT_NUMBER}@gcp-sa-ces.iam.gserviceaccount.com`.
4. **CX OpenAPI tool** pointing at `<service-url>/ask_race_data`, **Service agent ID token** auth, schema = the trimmed single-operation spec.
5. Configure **async** if/when tool latency consistently exceeds ~5s.
6. **(Optional showcase)** also deploy to Agent Engine (auto-registers in Agent Registry) and/or expose A2A via `to_a2a`.

### CX Agent Studio gotchas (for the student guide)

- CX Agent Studio is **not** found by searching the Cloud Console — go to **`ces.cloud.google.com`**, pick the project, "Create your first AI agent" (first creation takes a few minutes), then the designer opens.
- Add a tool: the **+** on the agent node → "Add new abilities with tools" → in the tool dialog, **+** → pick the tool type.
- Reference a tool inside instructions with **`{@TOOL: <toolName>_<operationId>}`** (e.g. a tool named `ask_race_data` with operation `ask_race_data` becomes `{@TOOL: ask_race_data_ask_race_data}`).
- Add instructions via the **+** on the agent node → "Add instructions".

## Open sub-question (cheap, parallelizable)

**#2b — Integration Connector → Firestore/BigQuery?** Only matters if we want the direct-connector contrast/stretch (CX → Firestore for trivial "now" lookups, bypassing the subagent). The CX tool menu does include an **Integration connector** type. Not the backbone — the subagent owns "now."
