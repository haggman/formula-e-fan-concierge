#!/usr/bin/env bash
# Deploy the race-data subagent to Cloud Run, PRIVATE, and let CX call it.
#
# WHERE: Cloud Shell (or any authed gcloud), repo root.
# WHAT:  bash deploy/deploy_race_data_subagent.sh
#
# The agent IS the service: ADK on Cloud Run serving POST /ask_race_data (the CX
# OpenAPI wire — see spec/cx_integration_spike.md). This script:
#   1. enables APIs + waits for the Run API to settle (fresh-project safe),
#   2. discovers TOOLBOX_URL (the deployed fe-toolbox) for LLM mode,
#   3. builds the image via Cloud Build (repo-root context; see cloudbuild.yaml),
#   4. deploys private (--no-allow-unauthenticated),
#   5. grants run.invoker to the CES service agent (so CX can invoke it),
#   6. grants the runtime SA Firestore + Vertex access (for live "now" + the LLM),
#   7. prints SERVICE_URL.
# Idempotent: safe to rerun. Same retry-on-propagation discipline as
# deploy/deploy_toolbox.sh.
#
# Knobs (env):
#   SUBAGENT_PACKAGE  solution.race_data_subagent (default) | starter.race_data_subagent
#   DETERMINISTIC     1 (default; no LLM/Toolbox/creds needed — first-light wire)
#                     0 (the real subagent: Firestore "now" + BigQuery "then")
#   REGION            us-central1 (default)
#   FE_MODEL          gemini-3.5-flash (default)
#   FE_STUB_RACE_TIME_S  900 (canned moment used when the data plane isn't up)
set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-race-data-subagent}"
RACE_ID="${RACE_ID:-berlin_2024_r10}"
DETERMINISTIC="${DETERMINISTIC:-1}"
FE_MODEL="${FE_MODEL:-gemini-3.5-flash}"
FE_STUB_RACE_TIME_S="${FE_STUB_RACE_TIME_S:-900}"
# Vertex location for the model — DISTINCT from the Cloud Run deploy REGION.
# Newer Gemini models are served from the 'global' endpoint (this is what
# activate.sh and the Ch2 engine build use); pointing it at the Cloud Run region
# (e.g. us-central1) 404s the model and only shows up in LLM mode. Override with
# GOOGLE_CLOUD_LOCATION=... if your model lives in a specific region.
GENAI_LOCATION="${GOOGLE_CLOUD_LOCATION:-global}"
SUBAGENT_PACKAGE="${SUBAGENT_PACKAGE:-solution.race_data_subagent}"
PKG_DIR="${SUBAGENT_PACKAGE//.//}"   # solution.race_data_subagent -> solution/race_data_subagent
IMAGE="gcr.io/${PROJECT_ID}/${SERVICE}:latest"

if [[ -z "$PROJECT_ID" ]]; then
    echo "ERROR: no project set. Run 'gcloud config set project YOUR_PROJECT'." >&2
    exit 1
fi
if [[ ! -d "$PKG_DIR" ]]; then
    echo "ERROR: SUBAGENT_PACKAGE=$SUBAGENT_PACKAGE -> $PKG_DIR not found." >&2
    exit 1
fi
gcloud config set project "$PROJECT_ID" >/dev/null
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"

echo "=================================================================="
echo "Project: $PROJECT_ID ($PROJECT_NUMBER)"
echo "Region:  $REGION"
echo "Service: $SERVICE   package: $SUBAGENT_PACKAGE   deterministic: $DETERMINISTIC"
echo "Image:   $IMAGE"
echo "=================================================================="

echo ">>> Enabling APIs..."
gcloud services enable \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    artifactregistry.googleapis.com \
    firestore.googleapis.com \
    aiplatform.googleapis.com \
    --project="$PROJECT_ID"

# On a brand-new project, `services enable` returns BEFORE the Run admin surface
# is queryable. Poll a cheap read so the rest runs unattended.
echo ">>> Waiting for Cloud Run API to settle..."
for attempt in 1 2 3 4 5 6; do
    gcloud run services list --region="$REGION" --project="$PROJECT_ID" --quiet >/dev/null 2>&1 && break
    echo "    ...Run API not serving yet — retry ${attempt}/6 in 10s"
    sleep 10
done

# --- TOOLBOX_URL (needed for LLM mode) ---
if [[ -z "${TOOLBOX_URL:-}" ]]; then
    echo ">>> Discovering TOOLBOX_URL (fe-toolbox)..."
    TOOLBOX_URL="$(gcloud run services describe fe-toolbox --region "$REGION" \
        --format='value(status.url)' 2>/dev/null || true)"
fi
if [[ "$DETERMINISTIC" == "0" && -z "$TOOLBOX_URL" ]]; then
    echo "ERROR: DETERMINISTIC=0 (LLM mode) needs TOOLBOX_URL, but fe-toolbox wasn't found." >&2
    echo "  Fix: run 'bash setup/all.sh' first (it deploys fe-toolbox), or export TOOLBOX_URL." >&2
    exit 1
fi
echo "    TOOLBOX_URL=${TOOLBOX_URL:-<unset — fine for DETERMINISTIC=1>}"

# --- 3. Build the image (repo-root context via cloudbuild.yaml) ---
echo ">>> Building image with Cloud Build..."
gcloud builds submit . \
    --project="$PROJECT_ID" \
    --config "solution/race_data_subagent/cloudbuild.yaml" \
    --substitutions "_IMAGE=${IMAGE},_PKG_DIR=${PKG_DIR}"

# --- 4. Deploy private to Cloud Run ---
echo ">>> Deploying to Cloud Run (private)..."
ENV_VARS="PROJECT_ID=${PROJECT_ID},GOOGLE_CLOUD_PROJECT=${PROJECT_ID}"
ENV_VARS="${ENV_VARS},GOOGLE_CLOUD_LOCATION=${GENAI_LOCATION},GOOGLE_GENAI_USE_VERTEXAI=1"
ENV_VARS="${ENV_VARS},RACE_ID=${RACE_ID},DETERMINISTIC=${DETERMINISTIC}"
ENV_VARS="${ENV_VARS},FE_MODEL=${FE_MODEL},FE_STUB_RACE_TIME_S=${FE_STUB_RACE_TIME_S}"
[[ -n "$TOOLBOX_URL" ]] && ENV_VARS="${ENV_VARS},TOOLBOX_URL=${TOOLBOX_URL}"

gcloud run deploy "$SERVICE" \
    --image="$IMAGE" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --no-allow-unauthenticated \
    --cpu=1 \
    --memory=1Gi \
    --cpu-boost \
    --timeout=120 \
    --max-instances=3 \
    --set-env-vars="$ENV_VARS" \
    --quiet

# --- 5. Let CX call it: grant run.invoker to the CES service agent ---
CES_SA="service-${PROJECT_NUMBER}@gcp-sa-ces.iam.gserviceaccount.com"
echo ">>> Granting run.invoker to the CES service agent (${CES_SA})..."
# The service agent is created on first CX use; force it so the grant can land.
gcloud beta services identity create --service=ces.googleapis.com --project="$PROJECT_ID" >/dev/null 2>&1 || true
granted=0
for attempt in 1 2 3 4 5 6; do
    if gcloud run services add-iam-policy-binding "$SERVICE" \
        --region="$REGION" --project="$PROJECT_ID" \
        --member="serviceAccount:${CES_SA}" \
        --role="roles/run.invoker" --quiet >/dev/null 2>&1; then
        granted=1; break
    fi
    echo "    ...IAM can't see ${CES_SA} yet (CES service agent propagating) — retry ${attempt}/6 in 10s"
    sleep 10
done
if [[ "$granted" != "1" ]]; then
    echo "WARN: could not grant run.invoker to ${CES_SA} after 6 attempts." >&2
    echo "      If you haven't opened CX Agent Studio in this project yet, do so once" >&2
    echo "      (it creates the service agent), then rerun this script." >&2
fi

# --- 6. Runtime SA: Firestore "now" + Vertex (for LLM mode) ---
RUNTIME_SA="$(gcloud run services describe "$SERVICE" --region "$REGION" \
    --format='value(spec.template.spec.serviceAccountName)' 2>/dev/null || true)"
[[ -z "$RUNTIME_SA" ]] && RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
echo ">>> Granting the runtime SA (${RUNTIME_SA}) Firestore + Vertex access..."
for role in roles/datastore.user roles/aiplatform.user; do
    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="serviceAccount:${RUNTIME_SA}" \
        --role="$role" --condition=None --quiet >/dev/null 2>&1 \
        && echo "    granted $role" \
        || echo "    WARN: could not grant $role to ${RUNTIME_SA} (rerun if LLM mode 403s)"
done

# --- 7. Read back the URL ---
URL=""
for attempt in 1 2 3 4 5 6; do
    URL="$(gcloud run services describe "$SERVICE" --region="$REGION" \
        --format='value(status.url)' --quiet 2>/dev/null || true)"
    [[ -n "$URL" ]] && break
    echo "    ...deployed, but describe isn't serving yet — retry ${attempt}/6 in 10s"
    sleep 10
done

echo ""
echo "=================================================================="
echo "Deployed (private)!"
echo "SERVICE_URL: ${URL:-<unreadable — rerun, it's idempotent>}"
echo "=================================================================="
echo ""
echo "Verify (authenticated proxy, since the service is private):"
echo "  gcloud run services proxy $SERVICE --region $REGION --port 8080 &"
echo "  curl -s -X POST http://localhost:8080/ask_race_data -H 'Content-Type: application/json' \\"
echo "       -d '{\"question\":\"how is car 13 doing right now?\"}' | python3 -m json.tool"
echo "  curl -s -X POST http://localhost:8080/ask_race_data -H 'Content-Type: application/json' \\"
echo "       -d '{\"question\":\"who wins the race?\"}' | python3 -m json.tool"
echo ""
echo "Then wire CX: paste ${PKG_DIR}/openapi_ask_race_data.yaml (SERVICE_URL=$URL)"
echo "into a CX OpenAPI tool with Service-agent-ID-token auth. See"
echo "spike/cx_openapi_spike/CX_WIRING.md and deploy/RUNBOOK_race_data_subagent.md."
echo ""
echo "Flip to the real agent when ready:  DETERMINISTIC=0 bash deploy/deploy_race_data_subagent.sh"
