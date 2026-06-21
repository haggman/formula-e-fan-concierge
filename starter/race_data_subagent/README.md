# Race-Data Subagent — STARTER

Build the ADK agent that owns Firestore **"now"** + BigQuery **"then"** (Berlin
R10 + 10-season career), **time-honest**, and is served to CX on Cloud Run as a
single `POST /ask_race_data` OpenAPI operation. The agent IS the service — there
is no separate wrapper. Reference: `solution/race_data_subagent/`. Full wire +
rationale: `spec/cx_integration_spike.md`.

## What you build vs what's given

**You build (the agent):**

- `tools/now_tools.py` — `get_field_now`, `get_car_now`, `get_recent_events`
  (field-wide Firestore reads, any car), plus `read_now` + `is_future_question`.
  Each "now" result carries `race_wall_time_ns`.
- `prompts.py` — the time-honesty doctrine + "now" vs "then" tool-choice rules.
- `config.py` — `RACE_START_EPOCH_NS` + `race_time_to_wall_ns` (the clock bridge;
  must match the commentator).
- `agent.py` — `root_agent`: now_tools + `ToolboxToolset` (the 14 Ch2 BQ tools) +
  the prompt.

**Given (don't rebuild):** `app.py` (the FastAPI/`get_fast_api_app` service +
`POST /ask_race_data`), `requirements.txt`, `openapi_ask_race_data.yaml` (the CX
schema), and the shared `Dockerfile`/`cloudbuild.yaml` + deploy script in
`deploy/`.

## Time-honesty (the whole point)

On every question: read a "now" tool first → take its `race_wall_time_ns` → pass
it as `through_time_ns` to **every** BigQuery call → never reveal anything after
the current moment. Derive `race_wall_time_ns` only from `race_time_s` (the clock
bridge), never from the real wall clock.

## Run / deploy

First-light with no model/creds (proves the wire + the future refusal):

```bash
DETERMINISTIC=1 uvicorn app:app --port 8080   # from this folder, after read_now() exists
```

Deploy your build to Cloud Run (data layer up first — `bash setup/all.sh`):

```bash
SUBAGENT_PACKAGE=starter.race_data_subagent bash deploy/deploy_race_data_subagent.sh
```

Then wire CX per `spike/cx_openapi_spike/CX_WIRING.md`. See
`solution/race_data_subagent/KNOWN_FIXES.md` for the gotchas (unique per-request
session id, PROJECT_ID vs number, etc.).
