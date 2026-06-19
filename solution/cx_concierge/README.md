# CX Concierge — reference build (Conversational Agents / CX Agent Studio)

The **pull** surface: an embedded chat that answers anything a fan asks. It is an
**orchestrator** — it owns no data itself; it routes to grounded tools.

This package is mostly **configuration + grounding assets**, because CX Agent Studio is
low-code. The "developer meat" is the MCP wire to the race-data subagent, the grounding
setup, and the auth. The app definition is built in the console and exported here
(`exportApp`/`importApp`) so it lives in version control.

## Tool surface (verified against current CX Agent Studio docs)

| Need | CX tool type | Notes |
|---|---|---|
| Race + stats ("how's car 13 now?", "Evans' recent seasons?") | **MCP tool** → race-data subagent | StreamableHttp `/mcp` on Cloud Run; Service Agent ID Token. **Recommended wire.** Async execution. |
| Team/driver **profiles** | **Data store / File search tool** (RAG) | curated profiles in `grounding/` → Vertex AI Search data store |
| Rules ("what's Attack Mode?") | **Data store / File search tool** (RAG) | curated rules pack in `grounding/` |
| Anything open-web / current | **Google Search tool** (grounding) | dissolves most of the bio/rules authoring burden |

Not used as the backbone: **Agent as a tool** (Preview; reuses an agent *inside the same
CX app*, not our external ADK subagent), **OpenAPI tool** (kept as the MCP fallback),
**Integration Connector** (a possible direct-Firestore contrast/stretch — not the backbone).

## The MCP tool wire (the spike — see spec/cx_integration_spike.md)

1. Deploy the race-data subagent MCP server to Cloud Run (StreamableHttp at `/mcp`).
2. Grant `roles/run.invoker` to the CX Agent Studio service account
   `service-{PROJECT_NUMBER}@gcp-sa-ces.iam.gserviceaccount.com`.
3. In the console: Tools → **MCP tool** → server address `https://<service>/mcp`,
   auth = **Service Agent ID Token**.
4. Set the tool to **async / long-running** execution (subagent does multiple LLM calls,
   can exceed the ~5s sync ceiling).
5. Add a playbook/agent instruction: route race/stats/now questions to this tool; route
   profile/rules questions to the data stores; fall back to Google Search.

## Grounding assets

See `grounding/README.md`. The profiles + rules pack are **authored** (the dataset has no
bio/rules corpus) in the Knowledge-Base & RAG conversation, then indexed into a Vertex AI
Search data store. This package holds the source docs; the data store is provisioned by a
setup step (to be added).

## Files

- `grounding/` — curated team/driver profiles + rules pack (source for the RAG data store).
- `app_config/` — exported CX app definition (`exportApp` JSON) once built. [placeholder]
- (no Python agent here — the concierge is a CX app, not ADK)
