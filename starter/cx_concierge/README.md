# CX Concierge — STARTER

You build the concierge in **CX Agent Studio** (low-code), then export the app definition
into `app_config/` so it's version-controlled.

**Follow the single build guide:** `solution/cx_concierge/BUILD_CONCIERGE.md` — it walks the
whole thing end to end (data stores → agent → tools → instructions → test → export), built
incrementally one tool at a time.

What you'll wire (Tier E grounding + the live wire):

1. **OpenAPI tool → race-data subagent.** Add a CX **OpenAPI** tool pointing at the deployed
   subagent's `POST /ask_race_data` (paste `solution/race_data_subagent/openapi_ask_race_data.yaml`
   with your `$SUBAGENT_URL`), **Service Agent ID Token** auth. Route live race / in-race stats
   here. (The spike chose OpenAPI over MCP — see `spec/cx_integration_spike.md`.)
2. **Data store tool** (`fe_knowledge`) over both the profiles and rules stores in
   `gs://class-demo/formula-e/grounding/` — for bios and rules.
3. **Google Search tool** for the open-web long tail.
4. **Instructions** that route each question type to the right tool, grounded and time-honest
   (never spoil the replay — not even via Google Search).

Reference build + lessons learned: `solution/cx_concierge/` (especially `BUILD_CONCIERGE.md`).
