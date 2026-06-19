# CX integration spike — Cloud Shell runbook (Part 1: deploy the agent)

Run these in **Cloud Shell** with the target project selected (so `gcloud` is already authed). This deploys the stub ADK agent to **Cloud Run** serving `POST /ask_race_data` (the OpenAPI wire CX will call), then proves it with `curl`. CX UI wiring is in `CX_WIRING.md` (Part 2).

The agent **is** the service — there's no separate wrapper. (Agent Engine can't expose a custom OpenAPI path; see `../../spec/cx_integration_spike.md`.)

## 0. Set your values

```bash
export PROJECT_ID="REPLACE_ME"            # the project ID (NOT the number)
export REGION="us-central1"               # Cloud Run + (later) Agent Engine region
export SERVICE="race-data-stub"
export RACE_ID="berlin_2024_r10"
gcloud config set project "$PROJECT_ID"
export PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
echo "project=$PROJECT_ID number=$PROJECT_NUMBER region=$REGION"
```

## 1. Enable APIs

```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  firestore.googleapis.com \
  aiplatform.googleapis.com
```

## 2. Deploy to Cloud Run (deterministic first-light, canned moment)

Deterministic mode + canned moment means this proves the **wire** end to end even before the simulator/Firestore "now" is up. From the repo root:

```bash
cd spike/cx_openapi_spike
gcloud run deploy "$SERVICE" \
  --source . \
  --region "$REGION" \
  --no-allow-unauthenticated \
  --set-env-vars "PROJECT_ID=${PROJECT_ID},RACE_ID=${RACE_ID},DETERMINISTIC=1,FE_STUB_RACE_TIME_S=900"
export SERVICE_URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')"
echo "SERVICE_URL=$SERVICE_URL"
```

Paste me the `SERVICE_URL` and any build errors.

## 3. Prove the wire with curl (authenticated)

The service is private, so test it through an authenticated proxy (avoids audience hassles):

```bash
# Terminal A — opens a local authenticated tunnel to the private service:
gcloud run services proxy "$SERVICE" --region "$REGION" --port 8080
```

```bash
# Terminal B (Cloud Shell: "+" to open another tab):
# 3a. live-moment question — expect refused_future=false and a real race_wall_time_ns
curl -s -X POST http://localhost:8080/ask_race_data \
  -H 'Content-Type: application/json' \
  -d '{"question":"how is car 13 doing right now?"}' | python3 -m json.tool

# 3b. future question — expect refused_future=true, no spoiler
curl -s -X POST http://localhost:8080/ask_race_data \
  -H 'Content-Type: application/json' \
  -d '{"question":"who wins the race?"}' | python3 -m json.tool

# 3c. the OpenAPI schema FastAPI serves (sanity)
curl -s http://localhost:8080/openapi.json | python3 -m json.tool | head -40
```

**Pass criteria:** 3a returns `"refused_future": false` with `race_wall_time_ns` = `1715519045726000000 + race_time_s*1e9` (for the canned 900s that's `1715519945726000000`); 3b returns `"refused_future": true` and no race outcome. `now_source` will say `canned` until the live plane is up.

Paste me both JSON responses.

## 4. Let CX call it — grant the CES service agent run.invoker

CX Agent Studio invokes Cloud Run as `service-{PROJECT_NUMBER}@gcp-sa-ces.iam.gserviceaccount.com` (verified against current CX docs). Grant it:

```bash
gcloud run services add-iam-policy-binding "$SERVICE" \
  --region "$REGION" \
  --member "serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-ces.iam.gserviceaccount.com" \
  --role "roles/run.invoker"
```

If that service-agent doesn't exist yet, create/trigger it once (it's auto-created when you first use CX Agent Studio in the project) and re-run:

```bash
gcloud beta services identity create --service=ces.googleapis.com --project="$PROJECT_ID" 2>/dev/null || true
```

Then go to `CX_WIRING.md`.

---

## 5. (Optional) Live "now" + the real LLM agent

Once the simulator/state-writer is populating `race_states/${RACE_ID}`, switch off canned + deterministic so it reads live and runs the actual ADK agent. The runtime SA needs Firestore + Vertex access:

```bash
export RUNTIME_SA="$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(spec.template.spec.serviceAccountName)')"
[ -z "$RUNTIME_SA" ] && export RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:${RUNTIME_SA}" --role roles/datastore.user
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:${RUNTIME_SA}" --role roles/aiplatform.user

gcloud run services update "$SERVICE" --region "$REGION" \
  --update-env-vars "DETERMINISTIC=0,GOOGLE_GENAI_USE_VERTEXAI=1,GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=${REGION},FE_MODEL=gemini-2.5-flash"
```

Re-run the curl checks: `now_source` should become `firestore`, `mode` should become `llm`. The LLM round trip will be slower — that's what motivates CX's **async** tool setting (Part 2). If `FE_MODEL` isn't available in your project, set it to a model that is.

## 6. (Optional showcase) A2A door + Agent Registry auto-registration

This is the "sexy" beat — **not** the CX wire. Two ways to show it:

- **A2A door on the same Cloud Run service:** add `--update-env-vars A2A_ENABLED=1`, redeploy, and the agent card is served under `/a2a`. (A2A is JSON-RPC + agent-card, not OpenAPI — CX can't consume it; this is for the agent-to-agent / registry story.)
- **Deploy the same agent to Agent Engine** (`agent_engines.create(...)` / `adk deploy`) and show it **auto-registers** in Agent Registry (Vertex AI Agent Engine agents register without extra config). Then open Agent Registry in the console to see it cataloged. Tell me when you want this and I'll write the exact Agent-Engine deploy snippet.
