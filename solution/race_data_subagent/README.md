# Race-Data Subagent (ADK) — reference solution

One intelligent agent that owns **both worlds** and is **time-honest**:

- **"Now"** — Firestore live state (the same `race_states`/`race_events` the commentator
  reads). "How's car 13 doing right now?"
- **"Then"** — BigQuery via the MCP Toolbox: this race (R10) **and** 10 seasons of career +
  race results. "How's Evans done over recent seasons?"

CX calls **this** subagent — never Firestore or BigQuery directly — so CX stays a pure
orchestrator. The subagent runs on **Cloud Run** and serves its own `POST /ask_race_data`
**OpenAPI** endpoint; CX reaches it via an **OpenAPI tool** with Service Agent ID Token auth
(validated live — see `spec/cx_integration_spike.md`).

## Why a subagent, not raw tools

The valuable questions (career arcs, "who to watch") are BigQuery, and "now" questions need
the live plane — fusing them with a single time bound is real work. Putting that behind one
agent gives CX one clean semantic tool (`ask_race_data`) and keeps time-honesty enforced in
one place. Pointing CX straight at the 14-tool Toolbox would leak complexity into CX and lose
the single enforcement point.

## Time-honesty (open #2 — resolved)

Reuse the Ch2 clock bridge verbatim (`config.race_time_to_wall_ns`, `RACE_START_EPOCH_NS`).
On every query the subagent:

1. Reads Firestore "now" first to learn the replay's current moment → `race_time_s`.
2. Converts to `race_wall_time_ns` (the original 2024 wall clock).
3. Passes that as the `through_time_ns` upper bound to **every** BigQuery Toolbox call.
4. The prompt forbids answering about anything after the current moment.

**Data range (confirmed):** all historical/career data is fair game — R10 **and** the full
10-season career/results — but everything is bounded to "up to this moment." Career data from
prior seasons is naturally ≤ the current wall moment, so the same single bound covers it. In
R10 itself the agent must not see the future. The bound enforces this mechanically; the prompt
reinforces it.

## The wire to CX (validated 2026-06-19 — OpenAPI on Cloud Run)

```
CX Agent Studio  ──OpenAPI tool (POST /ask_race_data, Service Agent ID Token)──►
   race-data subagent (ADK agent on Cloud Run — the agent IS the service)
       ├─ MCP Toolbox (BigQuery: R10 + career)        [reused from Ch2]
       └─ now_tools (Firestore "now", field-wide)     [new, small]
```

- Serve via ADK's `get_fast_api_app()` + a single `@app.post("/ask_race_data")` operation
  (FastAPI auto-serves `/openapi.json`). The agent is the service — **no separate wrapper**.
- Host: **Cloud Run**, deployed private. Auth: **Service Agent ID Token** — grant `run.invoker`
  to `service-{PROJECT_NUMBER}@gcp-sa-ces.iam.gserviceaccount.com` (the CES service agent).
  Same-project Cloud Run needs no extra IAM beyond that grant.
- Execution mode: multiple LLM/tool calls can exceed CX's ~5s sync ideal — set the CX tool to
  **async / long-running** (5–60s) when tool latency warrants. (A 6.7s simulator turn was
  tolerated with no async config in the spike.)
- Why OpenAPI (not MCP or A2A/registry): CX has no A2A/Agent-Registry tool type, and Agent
  Engine can't serve a custom OpenAPI path; MCP-on-Cloud-Run works but adds no payoff over
  plain OpenAPI for a student lab. Full reasoning + evidence in `spec/cx_integration_spike.md`.
- **Optional showcase:** also deploy to Agent Engine (auto-registers in Agent Registry) and/or
  expose an A2A door (`to_a2a(root_agent)`, ~1 line). Off the critical path.

## Serving layer (the "which app.py" decision)

`app.py` runs in two modes, chosen by the `DETERMINISTIC` env var:

- **`DETERMINISTIC=0` (the real subagent):** the app **is** ADK's
  `get_fast_api_app()` — the canonical "ADK agent on Cloud Run" surface (auto
  `/openapi.json`, the `/run*` + session endpoints). `POST /ask_race_data` runs
  the real `LlmAgent` (Firestore "now" + BigQuery "then") via a Runner. This is
  the spec wording, literally.
- **`DETERMINISTIC=1` (first-light, default):** the app is a plain FastAPI
  instance and `POST /ask_race_data` answers deterministically (read "now",
  refuse the future, echo the bridged wall time) — **no google-adk, no Vertex,
  no Toolbox needed.** It proves the CX → OpenAPI wire and the future-refusal on
  a fresh project before any creds, and it's what the local harness exercises.

Either way the single CX-facing operation is `POST /ask_race_data {question} ->
{answer, race_time_s, race_wall_time_ns, now_source, refused_future, mode}`, and
the agent IS the service (no wrapper). The validated spike used a plain FastAPI +
Runner throughout; this build keeps that proven invocation for `/ask_race_data`
(unique per-request session id) and adds `get_fast_api_app()` as the LLM-mode
shell to match the spec. To go plain-FastAPI-only, drop the `else` branch in
`app.py`.

**Package layout for `get_fast_api_app()`:** the package uses **relative**
internal imports so it loads both as `solution.race_data_subagent` (in the repo)
and as a top-level `race_data_subagent` agent folder under an ADK `agents_dir`
(in the container). `shared.*` stays absolute; the Dockerfile copies `shared/`
alongside. See `KNOWN_FIXES.md`.

## Run / deploy / verify

```bash
# Local first-light (no cloud): proves the wire + future refusal
pip install fastapi pydantic httpx
python scripts/verify_subagent_local.py

# Deploy to Cloud Run (data layer up first: bash setup/all.sh)
DETERMINISTIC=1 bash deploy/deploy_race_data_subagent.sh   # wire first
DETERMINISTIC=0 bash deploy/deploy_race_data_subagent.sh   # then the real agent
```

Full deploy + live-verification steps (live-moment answer + refused "who wins?")
are in `deploy/RUNBOOK_race_data_subagent.md`; CX UI wiring in
`spike/cx_openapi_spike/CX_WIRING.md`.

## Files

- `agent.py` — ADK agent: ToolboxToolset (the 14 Ch2 BQ tools) + now_tools (Firestore) + time-honest prompt.
- `config.py` — race scope + the time bridge (must match the commentator's constant).
- `prompts.py` — time-honesty doctrine + how to choose "now" vs "then" tools.
- `tools/now_tools.py` — field-wide Firestore "now" lookups (any car) + `read_now`/`is_future_question` for the deterministic path.
- `app.py` — the Cloud Run service: `get_fast_api_app()` (LLM) / plain FastAPI (deterministic) + the single `POST /ask_race_data`.
- `openapi_ask_race_data.yaml` — the trimmed single-operation schema to paste into the CX OpenAPI tool.
- `requirements.txt` — service deps (FastAPI, firestore, `google-adk[a2a]`, `toolbox-core`, aiplatform).
- `Dockerfile` + `cloudbuild.yaml` — repo-root-context build (needs `shared/`); `PKG_DIR` selects starter/solution.
- `KNOWN_FIXES.md` — gotchas (superseded `mcp_server.py`, per-request session id, PROJECT_ID 404, layout, …).
- Deploy: `deploy/deploy_race_data_subagent.sh`; verify: `scripts/verify_subagent_local.py` + `deploy/RUNBOOK_race_data_subagent.md`.
- See `spike/cx_openapi_spike/` for the validated reference implementation of this wire.
