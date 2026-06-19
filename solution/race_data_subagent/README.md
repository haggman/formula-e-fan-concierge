# Race-Data Subagent (ADK) — reference solution

One intelligent agent that owns **both worlds** and is **time-honest**:

- **"Now"** — Firestore live state (the same `race_states`/`race_events` the commentator
  reads). "How's car 13 doing right now?"
- **"Then"** — BigQuery via the MCP Toolbox: this race (R10) **and** 10 seasons of career +
  race results. "How's Evans done over recent seasons?"

CX calls **this** subagent — never Firestore or BigQuery directly — so CX stays a pure
orchestrator. The subagent is exposed to CX as an **MCP tool** (see
`spec/cx_integration_spike.md`).

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

## The MCP wire to CX (recommended path)

```
CX Agent Studio  ──MCP (StreamableHttp, /mcp, Service Agent ID Token)──►
   race-data subagent MCP server (Cloud Run)  ──►  ADK agent
       ├─ MCP Toolbox (BigQuery: R10 + career)        [reused from Ch2]
       └─ now_tools (Firestore "now", field-wide)     [new, small]
```

- Transport: **StreamableHttp** only (CX does not support SSE). Server URL ends `/mcp`.
- Host: **Cloud Run**. Auth: **Service Agent ID Token** — grant `run.invoker` to
  `service-{PROJECT_NUMBER}@gcp-sa-ces.iam.gserviceaccount.com` (the CX Agent Studio SA).
  This is the same IAM pattern as Ch2's Pub/Sub push auth.
- Execution mode: the subagent does multiple LLM/tool calls, so a round trip can exceed the
  ~5s sync ceiling — configure the CX tool for **async / long-running** execution.
- Fallback wire: **OpenAPI tool** (same auth options) if MCP is blocked. See the spike.

## Files

- `agent.py` — ADK agent: ToolboxToolset (BQ) + now_tools (Firestore) + time-honest prompt.
- `config.py` — race scope + the time bridge (must match the commentator's constant).
- `prompts.py` — time-honesty doctrine + how to choose "now" vs "then" tools.
- `tools/now_tools.py` — field-wide Firestore "now" lookups (any car, not just #13).
- `mcp_server.py` — FastMCP StreamableHttp wrapper exposing `ask_race_data(question)`.
- `Dockerfile` — container for the Cloud Run MCP server.
