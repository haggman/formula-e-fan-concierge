# CX Concierge — STARTER

You build the concierge in **CX Agent Studio** (low-code), then export the app definition
into `app_config/` so it's version-controlled. Reference build: `solution/cx_concierge/`.

What you'll wire (Tier E, with the live wire as Tier F or core):

1. **MCP tool → race-data subagent.** Deploy the subagent's MCP server (Cloud Run,
   StreamableHttp `/mcp`), grant `run.invoker` to the CX service agent, add an MCP tool
   pointing at `https://<service>/mcp` with **Service Agent ID Token** auth. Set it
   **async**. Route race/stats/now questions here.
2. **Data store / File search tools** over the profiles + rules pack in `grounding/`.
3. **Google Search tool** for grounding the long tail.
4. Playbook/agent instructions that route each question type to the right tool.

See `spec/cx_integration_spike.md` for the exact wire and the validation steps.
