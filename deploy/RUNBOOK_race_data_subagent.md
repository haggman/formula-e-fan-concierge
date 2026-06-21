# Race-data subagent — deploy & verify runbook

End-to-end from a **fresh GCP project**: stand up the data layer, deploy the
subagent (the agent IS the service — ADK on Cloud Run serving `POST
/ask_race_data`), prove it live (a live-moment answer + a refused "who wins?"),
then wire CX. Run everything in **Cloud Shell** from the repo root with the
target project selected.

The wire and auth were validated in the spike (`spec/cx_integration_spike.md`);
this is the real build of that wire.

## 0. Select the project + activate

```bash
gcloud config set project YOUR_PROJECT_ID
export REGION=us-central1
source activate.sh                      # venv + PROJECT_ID/REGION + TOOLBOX_URL discovery
```

## 1. Stand up the data layer first (the subagent talks to it)

The subagent reads Firestore "now" and calls BigQuery via fe-toolbox, so the data
plane must exist before LLM mode can answer. This is the Ch2 data layer, kept
as-is (`spec`/architecture: keep setup steps 1–6):

```bash
bash setup/all.sh        # 1 enable APIs · 2 load BigQuery · 3 fe-toolbox ·
                         # 4 Firestore · 5 state writer · 6 simulator · verify
source activate.sh       # re-source so TOOLBOX_URL (fe-toolbox) is in your shell
echo "TOOLBOX_URL=$TOOLBOX_URL"
```

Budget ~10–20 min on a fresh project (Firestore index builds are the variable).
`setup/all.sh` is idempotent — rerun after any failure.

## 2. Deploy the subagent — DETERMINISTIC first-light (proves the wire, no LLM)

Deterministic mode answers without the model/Toolbox/creds, so it proves the CX →
OpenAPI wire and the future-refusal even before Vertex is exercised. It also
grants `run.invoker` to the CES service agent and the runtime SA's Firestore +
Vertex roles, so flipping to the real agent later is just a redeploy.

```bash
DETERMINISTIC=1 bash deploy/deploy_race_data_subagent.sh
# note the printed SERVICE_URL
```

Deploy the **student** build instead of the reference with
`SUBAGENT_PACKAGE=starter.race_data_subagent`.

## 3. Prove the wire with curl (authenticated; the service is private)

```bash
# Terminal A — authenticated local tunnel to the private service:
gcloud run services proxy race-data-subagent --region "$REGION" --port 8080
```

```bash
# Terminal B (Cloud Shell: "+" for a new tab):
# 3a. live-moment — expect refused_future=false and a real race_wall_time_ns
curl -s -X POST http://localhost:8080/ask_race_data -H 'Content-Type: application/json' \
  -d '{"question":"how is car 13 doing right now?"}' | python3 -m json.tool

# 3b. future — expect refused_future=true, no spoiler
curl -s -X POST http://localhost:8080/ask_race_data -H 'Content-Type: application/json' \
  -d '{"question":"who wins the race?"}' | python3 -m json.tool

# 3c. the OpenAPI schema FastAPI serves (sanity)
curl -s http://localhost:8080/openapi.json | python3 -m json.tool | head -40
```

**Pass criteria:** 3a → `"refused_future": false` with `race_wall_time_ns` =
`1715519045726000000 + race_time_s*1e9`; 3b → `"refused_future": true` and no
outcome. `now_source` is `firestore` if the simulator is running, else `canned`.

## 4. Flip to the real agent (Firestore "now" + BigQuery "then", LLM)

```bash
DETERMINISTIC=0 bash deploy/deploy_race_data_subagent.sh
```

Re-run the curls: `mode` becomes `llm`, `now_source` becomes `firestore`, and the
answers are real (car 13's actual position/energy; career stats on request). The
LLM round trip is slower (~7–9s observed in the spike) — fine synchronously; set
CX's tool to async/long-running only if latency climbs toward ~60s.

If 3a/3b 403 in LLM mode, the runtime SA is missing a role — rerun the deploy
(it grants `datastore.user` + `aiplatform.user` idempotently) or see
`solution/race_data_subagent/KNOWN_FIXES.md`.

## 5. Wire CX

In CX Agent Studio (`ces.cloud.google.com`), add an **OpenAPI** tool: paste
`solution/race_data_subagent/openapi_ask_race_data.yaml` with `SERVICE_URL`
replaced by your `SERVICE_URL`, auth = **Service agent ID token**. Full UI steps
(and the `{@TOOL: ...}` instruction reference) are in
`spike/cx_openapi_spike/CX_WIRING.md`. Simulator checks: "How's car 13 right
now?" answers; "Who wins?" refuses.

## Notes

- **Private deploy:** the service is `--no-allow-unauthenticated`; only the CES
  service agent (granted `run.invoker`) and your authed proxy can call it.
- **Same-project CX** needs only that `run.invoker` grant (no extra audience
  config). Cross-project would add the standard ID-token audience steps.
- **Per-request session id:** a fixed session id throws `AlreadyExistsError` on
  warm instances — the service mints a unique one per request. (KNOWN_FIXES.md.)
