# CX integration spike — CX Agent Studio wiring (Part 2, UI)

All UI, in the **Conversational Agents / CX Agent Studio** console. Do Part 1 (`RUNBOOK.md`) first and have your `SERVICE_URL` handy.

## Step A — Confirm the tool menu (our live evidence check)

Before wiring, we settle the open architecture question by looking at the actual UI.

1. Open the Conversational Agents console, select (or create) your agent/app.
2. Go to **Tools** → click **+ Create** (or the create-tool button on the right of the agent builder).
3. **Read the list of tool types offered** and tell me what you see. We expect: Agent-as-a-tool, Client function, Data store, File search, Google Search, Integration Connector, MCP, OpenAPI, Python code, Salesforce, ServiceNow, System, Widget.

   **The thing we're checking:** is there any **A2A**, **Agent Registry**, or **"add a registered/Agent-Engine agent"** option? Per current docs there isn't (CX can't natively consume A2A/registry agents — that's why we're using OpenAPI), but the console sometimes ships ahead of docs. Paste me the exact list. This is the evidence that locks the spec.

## Step B — Add the OpenAPI tool

1. Tool type: **OpenAPI**.
2. Name: `ask_race_data` (or `race_data_subagent`).
3. **Schema:** paste the contents of `openapi_ask_race_data.yaml`, with `SERVICE_URL` replaced by your Cloud Run URL (no trailing slash). It's intentionally a **single operation** — CX allows only one operation per OpenAPI tool.
4. **Authentication:** choose **Service agent ID token**. This makes CX call the service as `service-{PROJECT_NUMBER}@gcp-sa-ces.iam.gserviceaccount.com` — the identity you granted `run.invoker` in Part 1 step 4. (No key, no SA file.)
5. Save. If the UI offers a **Test**/try-it on the tool, send `{"question":"how is car 13 doing right now?"}` and confirm a 200 with `refused_future:false`. Paste the result.

## Step C — Tell the agent to use it

In the agent's instructions / playbook, add a line so the orchestrator routes race/stats/now questions to the tool, e.g.:

> When the user asks about the race, a car, standings, statistics, or what's happening "right now", call the `ask_race_data` tool with their question and answer from its `answer` field. Never answer race facts from your own knowledge, and never reveal anything the tool refuses.

Save / re-train if prompted.

## Step D — Execution mode (async / long-running)

The deterministic stub answers fast, but the real LLM+tools round trip can exceed CX's ~5s synchronous guidance (async is meant for ~5–60s).

1. On the tool (or the tool-use settings), set execution to **asynchronous / long-running** if the option is present. Tell me the exact label/options you see so I can record it.
2. We'll exercise this for real once the service is in LLM mode (Part 1 step 5).

## Step E — Simulator checks (the spike's success criteria)

Open the **Simulator** / preview and run:

1. **Live moment:** "How's car 13 right now?" → the agent calls `ask_race_data` and answers with the current moment. Confirm in the tool-call trace that it hit your Cloud Run service. ✅ discovery + auth + live-moment answer.
2. **Async (>5s):** after switching to LLM mode (Part 1 step 5), ask a question that makes it think; confirm it waits and returns rather than timing out. ✅ async behavior.
3. **Time-honesty:** "Who wins the race?" → must refuse / decline to spoil. ✅ future leak blocked.

Paste me the simulator transcript + the tool-call trace for each. Then I finalize the spec with which path succeeded.

## If Step B auth fails (401/403)

- Re-check Part 1 step 4 ran for **this** project's `gcp-sa-ces` service agent and that `PROJECT_NUMBER` is correct.
- Confirm the service agent exists: it's created on first CX use; if missing, the `gcloud beta services identity create --service=ces.googleapis.com` line in Part 1 step 4 forces it.
- Tell me the exact error and I'll adjust.
