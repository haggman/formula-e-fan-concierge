# Race-data subagent — known fixes & gotchas

Things that bit us (or would have) building this package. Most carry straight
over to students, so they're worth keeping in the lab notes.

## 1. `mcp_server.py` was superseded by the OpenAPI wire — removed

The scaffold shipped an `mcp_server.py` (a FastMCP StreamableHttp `/mcp` server)
from *before* the CX integration spike. The spike (2026-06-19, validated live)
chose **OpenAPI**, not MCP: CX has a first-class OpenAPI tool, the single
`ask_race_data` operation maps to CX's "one operation per tool" rule, and MCP
adds the StreamableHttp mental model for no student payoff. See
`spec/cx_integration_spike.md`.

So `mcp_server.py` is **deleted** from both `solution/` and `starter/` and
replaced by `app.py`: ADK's `get_fast_api_app()` (LLM mode) / a plain FastAPI
app (deterministic mode) serving the single `POST /ask_race_data`. The agent IS
the service — no separate wrapper. (MCP-on-Cloud-Run still works and is noted in
the spec as "works, not chosen" if Toolbox symmetry is ever wanted.)

## 2. Unique per-request session id (the "tool test works, agent call fails" bug)

A module-level session service with a **fixed** session id throws
`AlreadyExistsError` on the 2nd+ request to a warm Cloud Run instance — the first
(cold) request creates the session, every later one collides. This is exactly
why a CX **tool test** passes (it hits a cold first-request) but the **agent
call** fails (it hits the warm instance). `app._run_llm` mints a unique
`cx-{uuid}` session id per request. Don't "optimize" this back to a constant.

## 3. PROJECT_ID vs project NUMBER → Firestore 404

On managed runtimes `GOOGLE_CLOUD_PROJECT` can arrive as the project **NUMBER**,
which makes Firestore 404 with a misleading "database (default) does not exist".
`shared/state_client.py` prefers `PROJECT_ID` (always the ID) and warns if the
resolved value is all digits. The deploy script sets `PROJECT_ID` explicitly.

## 4. Time-honesty is mechanical, not vibes (the Ch2 "AgentEvent" lesson)

`race_wall_time_ns` is derived ONLY from the replay's `race_time_s` via
`config.race_time_to_wall_ns` — never from the host's real (2026) wall clock. So
a real-world timestamp can't leak in as a BigQuery `through_time_ns` bound; the
upper bound is always the replay moment. The prompt makes the model pass that
bound to every BQ tool and refuse the future; the bound is what actually hides
it. `now_tools.get_recent_events` also caps `to_race_time_s` at the current
moment so live events can't spoil either.

## 5. ToolboxToolset binds its HTTP client to the first event loop it runs on

In a script that spins a fresh loop per question this causes "Event loop is
closed" after the first turn (see `scripts/agent_chat.py`). In this service it's
a non-issue: uvicorn runs one event loop for the process and the `/ask_race_data`
route is async, so every agent run shares that loop. The Runner is a lazy
singleton created on first request, on that loop.

## 6. Package layout for `get_fast_api_app()` — relative imports + agents_dir

`get_fast_api_app(agents_dir=...)` inserts `agents_dir` on `sys.path` and imports
each subfolder as a **top-level** agent package. So the package's internal
imports are **relative** (`from .prompts import ...`, `from ..config import ...`),
which lets it load both as `solution.race_data_subagent` (in the repo) and as a
top-level `race_data_subagent` (in the container). `shared.*` stays an absolute
top-level import; the Dockerfile copies `shared/` alongside. `app.py` lives at
the WORKDIR root with the package under `./agents/race_data_subagent/`.

## 7. Build context must be the repo root (needs shared/)

The Dockerfile copies `shared/` next to the package, so its build context is the
**repo root**, which means `gcloud run deploy --source` (it wants a Dockerfile at
the source root) won't do. The deploy script builds via Cloud Build using
`cloudbuild.yaml` (`docker build -f solution/race_data_subagent/Dockerfile .`)
then deploys the resulting image.

## 8. ToolboxToolset needs the `[toolbox]` extra (toolbox-adk)

`google-adk[a2a]` alone is NOT enough — importing `agent.py` then fails at
container start with: *"ToolboxToolset requires the 'toolbox-adk' package.
Please install it using `pip install google-adk[toolbox]`."* Fixed by
`google-adk[a2a,toolbox]>=1.29.0` in `requirements.txt`.

## 9. Deterministic container must NOT import the agent (TOOLBOX_URL is set)

The deploy script sets `TOOLBOX_URL` even for the `DETERMINISTIC=1` first-light
deploy (so flipping to LLM mode is just a redeploy). The old `__init__.py` guard
(`adk installed AND TOOLBOX_URL`) therefore fired in deterministic mode too:
importing `now_tools` runs the package `__init__`, which imported `agent.py`,
which builds a `ToolboxToolset` at import → the crash in #8, in a mode that
doesn't even use the agent. Fix: the guard also requires `DETERMINISTIC != "1"`,
so the deterministic container never touches the LLM agent / ToolboxToolset. (The
local harness didn't catch this because the sandbox has no `google-adk`
installed, so the guard's `find_spec` short-circuited — worth deploying once, or
installing google-adk locally, to exercise the real import path.)

## 10. Two modes, and why deterministic exists

`DETERMINISTIC=1` (default) answers without the LLM/Vertex/Toolbox — it proves
the CX → OpenAPI wire and the future-refusal end to end on a fresh project before
the data plane or model creds are in place, and it's what the local verification
harness (`scripts/verify_subagent_local.py`) exercises. Flip to
`DETERMINISTIC=0` once `TOOLBOX_URL` + Vertex are set to run the real agent.
