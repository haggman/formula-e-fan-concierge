#!/usr/bin/env bash
# Deploy the pit-wall frontend to Cloud Run (chunk 13, pass 2).
#
# WHERE: Cloud Shell (Qwiklabs student account), repo root, venv active
# WHAT:  bash deploy/deploy_frontend.sh
#
# Idempotent: re-running rebuilds the image and updates the service.
#
# Two Cloud Run settings here are LOAD-BEARING, not tuning:
#   --min-instances=1 --max-instances=1
#       The engineer loop and state poller are BACKGROUND TASKS inside the
#       service. Scale-to-zero kills the engineer; a second instance is a
#       second engineer making duplicate radio calls. Exactly one.
#   --no-cpu-throttling
#       Background tasks need CPU BETWEEN requests. Default request-based
#       throttling would freeze the trigger loop whenever no HTTP request
#       is in flight. (This switches the service to instance-based billing.)

set -euo pipefail

SERVICE_NAME="${SERVICE_NAME:-fe-frontend}"
SA_NAME="${SA_NAME:-fe-frontend-sa}"
REPO_NAME="${REPO_NAME:-fe-services}"

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
if [[ -z "$PROJECT_ID" ]]; then
    echo "ERROR: PROJECT_ID env var required. Run: source activate.sh" >&2
    exit 1
fi
if [[ -z "${REGION:-}" ]]; then
    echo "ERROR: REGION env var required. Run: source activate.sh" >&2
    exit 1
fi

SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Which agent package the deployed frontend resolves prompts/config/persona
# through. Default: the reference. Bonus path:
#   export DEPLOY_AGENT_PACKAGE=starter.race_engineer
# ships YOUR agent with the deployed pit wall.
DEPLOY_AGENT_PACKAGE="${DEPLOY_AGENT_PACKAGE:-solution.race_engineer}"

# --- The deployed engine (required: this frontend runs AGENT_MODE=engine) ---
ENGINE_FILE="${REPO_ROOT}/deploy/.engine_resource"
if [[ ! -f "$ENGINE_FILE" ]]; then
    echo "ERROR: ${ENGINE_FILE} not found — run deploy/deploy_agent_engine.sh first." >&2
    exit 1
fi
ENGINE_RESOURCE="$(tr -d '[:space:]' < "$ENGINE_FILE")"

# --- The simulator (for the SIM control bar proxy) ---
# REQUIRED: an empty SIM_URL gets baked into the service env and every
# SIM-bar call 503s ("SIM_URL not configured") — and in engine mode the
# frontend's loud local-mode startup guard never trips, so the broken wall
# comes up looking healthy. Discovery retries absorb transient gcloud
# failures (the Finding #11 mechanism); still empty after that means the
# simulator genuinely isn't deployed, which is a hard stop, not a WARN.
if [[ -z "${SIM_URL:-}" ]]; then
    for attempt in 1 2 3 4 5 6; do
        SIM_URL="$(gcloud run services describe fe-simulator --region "$REGION" --project="$PROJECT_ID" --format='value(status.url)' --quiet 2>/dev/null || true)"
        [[ -n "$SIM_URL" ]] && break
        echo "    ...can't read fe-simulator URL yet (transient gcloud / propagation) — retry ${attempt}/6 in 10s"
        sleep 10
    done
fi
if [[ -z "$SIM_URL" ]]; then
    echo "ERROR: fe-simulator not found in ${REGION} — deploying without it ships a" >&2
    echo "       pit wall whose SIM bar 503s on everything. Run setup/all.sh (or" >&2
    echo "       setup/6_deploy_simulator.sh) first, then rerun this script." >&2
    exit 1
fi

echo "=================================================================="
echo "Project: $PROJECT_ID"
echo "Region:  $REGION"
echo "Service: $SERVICE_NAME"
echo "SA:      $SA_EMAIL"
echo "Engine:  $ENGINE_RESOURCE"
echo "Sim:     ${SIM_URL:-<none>}"
echo "AgentPkg: ${DEPLOY_AGENT_PACKAGE}"
echo "=================================================================="

# --- Enable APIs ---
echo ">>> Enabling APIs..."
gcloud services enable \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    artifactregistry.googleapis.com \
    aiplatform.googleapis.com \
    firestore.googleapis.com \
    texttospeech.googleapis.com \
    speech.googleapis.com \
    --project="$PROJECT_ID"

# --- Wait for the Cloud Run admin API to actually serve ---
# On a brand-new project, `services enable` returns BEFORE the Run admin
# surface is queryable, so the first deploy/describe call can hit
# SERVICE_DISABLED and drop an interactive "enable and retry? (y/N)" prompt.
# Poll a cheap read until it stops failing so the rest runs unattended.
echo ">>> Waiting for Cloud Run API to settle..."
for attempt in 1 2 3 4 5 6; do
    gcloud run services list --region="$REGION" --project="$PROJECT_ID" --quiet >/dev/null 2>&1 && break
    echo "    ...Run API not serving yet — retry ${attempt}/6 in 10s"
    sleep 10
done

# --- Service account ---
echo ">>> Ensuring service account exists..."
if ! gcloud iam service-accounts describe "$SA_EMAIL" --project="$PROJECT_ID" >/dev/null 2>&1; then
    gcloud iam service-accounts create "$SA_NAME" \
        --display-name="Formula E Pit-Wall Frontend" \
        --project="$PROJECT_ID"
    echo "    created SA $SA_EMAIL"
else
    echo "    SA $SA_EMAIL exists"
fi

# --- IAM grants ---
# datastore.user  — Firestore reads (state poller + engineer loop)
# aiplatform.user — invoke the Agent Engine
# speech.client   — Speech-to-Text V2 recognize (push-to-talk); unlike TTS,
#                   STT recognizers are IAM resources, so the SA needs this.
#                   (Worked in Cloud Shell only via the student account's
#                   broad roles — classic dev-vs-deployed IAM gap.)
echo ">>> Granting roles..."
for role in roles/datastore.user roles/aiplatform.user roles/speech.client; do
    # New SAs can take tens of seconds to propagate into IAM on a fresh
    # project — retry instead of dying on "Service account ... does not exist".
    granted=0
    for attempt in 1 2 3 4 5 6; do
        if gcloud projects add-iam-policy-binding "$PROJECT_ID" \
            --member="serviceAccount:${SA_EMAIL}" \
            --role="$role" \
            --condition=None \
            --quiet >/dev/null 2>&1; then
            granted=1
            break
        fi
        echo "    ...IAM can't see ${SA_EMAIL} yet (new SA propagating) — retry ${attempt}/6 in 10s"
        sleep 10
    done
    if [[ "$granted" != "1" ]]; then
        echo "ERROR: failed to grant $role to ${SA_EMAIL} after 6 attempts" >&2
        exit 1
    fi
    echo "    granted $role"
done

# --- Artifact Registry repo (shared with state-writer images) ---
if ! gcloud artifacts repositories describe "$REPO_NAME" \
        --location="$REGION" \
        --project="$PROJECT_ID" >/dev/null 2>&1; then
    gcloud artifacts repositories create "$REPO_NAME" \
        --location="$REGION" \
        --repository-format=docker \
        --description="Formula E race engineer services" \
        --project="$PROJECT_ID"
    echo "    created Artifact Registry repo $REPO_NAME"
else
    echo "    repo $REPO_NAME exists"
fi

# --- Build the container image with Cloud Build ---
echo ">>> Building container image..."
IMAGE_TAG="$(date -u +%Y%m%d-%H%M%S)"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/frontend:${IMAGE_TAG}"

CB_CONFIG="$(mktemp)"
cat > "$CB_CONFIG" <<EOF
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', '${IMAGE}', '-f', 'frontend/Dockerfile', '.']
images: ['${IMAGE}']
EOF

gcloud builds submit "$REPO_ROOT" \
    --config="$CB_CONFIG" \
    --project="$PROJECT_ID"

rm -f "$CB_CONFIG"
echo "    built and pushed: $IMAGE"

# --- Deploy Cloud Run service ---
echo ">>> Deploying Cloud Run service..."
gcloud run deploy "$SERVICE_NAME" \
    --image="$IMAGE" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --service-account="$SA_EMAIL" \
    --allow-unauthenticated \
    --cpu=1 \
    --memory=1Gi \
    --no-cpu-throttling \
    --min-instances=1 \
    --max-instances=1 \
    --concurrency=80 \
    --timeout=3600 \
    --session-affinity \
    --set-env-vars="AGENT_MODE=engine,AGENT_ENGINE_RESOURCE=${ENGINE_RESOURCE},GOOGLE_CLOUD_PROJECT=${PROJECT_ID},PROJECT_ID=${PROJECT_ID},RACE_ID=berlin_2024_r10,SIM_URL=${SIM_URL},AGENT_PACKAGE=${DEPLOY_AGENT_PACKAGE}" \
    --quiet

# Post-deploy describe can hit a stale API frontend (SERVICE_DISABLED
# seconds after a successful deploy — enablement propagates per replica).
# The deploy already succeeded; never let the readback kill the script.
URL=""
for attempt in 1 2 3 4 5 6; do
    URL="$(gcloud run services describe "$SERVICE_NAME" --region="$REGION" --project="$PROJECT_ID" --format='value(status.url)' --quiet 2>/dev/null || true)"
    [[ -n "$URL" ]] && break
    echo "    ...deployed, but describe isn't serving yet (API propagation) — retry ${attempt}/6 in 10s"
    sleep 10
done
if [[ -z "$URL" ]]; then
    echo "ERROR: ${SERVICE_NAME} deployed but its URL is unreadable after 6 tries — rerun this script (idempotent)." >&2
    exit 1
fi

echo ""
echo "=================================================================="
echo "Deployed!"
echo "Pit wall: $URL"
echo "=================================================================="
echo ""
echo "Notes:"
echo "  - min=max=1 instance + no-cpu-throttling: the engineer loop is a"
echo "    background task — this keeps exactly one running, always."
echo "  - Websocket idle timeout is 3600s; the browser reconnects anyway."
echo "  - Toolbox auth flip (pass 3) is separate: deploy/lockdown_toolbox.sh"