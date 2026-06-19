#!/usr/bin/env bash
# Deploy the Formula E simulator to Cloud Run.
# Idempotent: creates Pub/Sub topic if missing, creates service account if missing,
# grants necessary roles, and deploys (or updates) the service.

set -euo pipefail

# --- Config (override via env) ---
SERVICE_NAME="${SERVICE_NAME:-fe-simulator}"
REGION="${REGION:-us-central1}"
TOPIC_NAME="${TOPIC_NAME:-fe-telemetry}"
SA_NAME="${SA_NAME:-fe-simulator-sa}"
FRAMES_BUCKET="${FRAMES_BUCKET:-class-demo}"
FRAMES_PATH="${FRAMES_PATH:-formula-e/r10/simulator/frames_v3.jsonl.gz}"
REPLAY_SPEED_MULTIPLIER="${REPLAY_SPEED_MULTIPLIER:-1.0}"
AUTO_RESTART="${AUTO_RESTART:-false}"

PROJECT_ID="$(gcloud config get-value project 2>/dev/null)"
if [[ -z "$PROJECT_ID" ]]; then
    echo "ERROR: no project set. Run 'gcloud config set project YOUR_PROJECT'." >&2
    exit 1
fi

SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "=================================================================="
echo "Project: $PROJECT_ID"
echo "Region:  $REGION"
echo "Service: $SERVICE_NAME"
echo "Topic:   $TOPIC_NAME"
echo "SA:      $SA_EMAIL"
echo "Frames:  gs://${FRAMES_BUCKET}/${FRAMES_PATH}"
echo "=================================================================="

# --- Enable required APIs ---
echo ">>> Enabling APIs..."
gcloud services enable \
    run.googleapis.com \
    pubsub.googleapis.com \
    cloudbuild.googleapis.com \
    artifactregistry.googleapis.com \
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

# --- Pub/Sub topic ---
echo ">>> Ensuring Pub/Sub topic exists..."
if ! gcloud pubsub topics describe "$TOPIC_NAME" --project="$PROJECT_ID" >/dev/null 2>&1; then
    gcloud pubsub topics create "$TOPIC_NAME" --project="$PROJECT_ID"
    echo "    created topic $TOPIC_NAME"
else
    echo "    topic $TOPIC_NAME exists"
fi

# --- Service account ---
echo ">>> Ensuring service account exists..."
if ! gcloud iam service-accounts describe "$SA_EMAIL" --project="$PROJECT_ID" >/dev/null 2>&1; then
    gcloud iam service-accounts create "$SA_NAME" \
        --display-name="Formula E Simulator" \
        --project="$PROJECT_ID"
    echo "    created SA $SA_EMAIL"
else
    echo "    SA $SA_EMAIL exists"
fi

# --- IAM grants ---
echo ">>> Granting roles..."
# Pub/Sub publisher. New SAs can take tens of seconds to propagate into
# IAM on a fresh project — retry instead of dying on "Service account ...
# does not exist". (Finding #12: the same propagation race the other
# deploy scripts handle; this topic-level binding was the missed surface.)
granted=0
for attempt in 1 2 3 4 5 6; do
    if gcloud pubsub topics add-iam-policy-binding "$TOPIC_NAME" \
        --member="serviceAccount:${SA_EMAIL}" \
        --role="roles/pubsub.publisher" \
        --project="$PROJECT_ID" >/dev/null 2>&1; then
        granted=1
        break
    fi
    echo "    ...IAM can't see ${SA_EMAIL} yet (new SA propagating) — retry ${attempt}/6 in 10s"
    sleep 10
done
if [[ "$granted" != "1" ]]; then
    echo "ERROR: failed to grant roles/pubsub.publisher to ${SA_EMAIL} after 6 attempts" >&2
    exit 1
fi
echo "    granted roles/pubsub.publisher"

# Frames bucket: gs://class-demo is PUBLIC-READ (allUsers objectViewer),
# so no per-SA grant is needed — and a cross-project student account
# couldn't bind IAM on it anyway (the old attempt printed a scary but
# harmless ERROR). If you ever point FRAMES_BUCKET at a private bucket,
# grant the SA roles/storage.objectViewer on it from the bucket's project.
echo "    frames bucket gs://${FRAMES_BUCKET} is public-read — no grant needed"

# --- Deploy ---
echo ">>> Deploying Cloud Run service..."
gcloud run deploy "$SERVICE_NAME" \
    --source=. \
    --quiet \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --service-account="$SA_EMAIL" \
    --allow-unauthenticated \
    --min-instances=1 \
    --max-instances=1 \
    --cpu=1 \
    --memory=512Mi \
    --no-cpu-throttling \
    --concurrency=10 \
    --timeout=3600 \
    --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT_ID},PUBSUB_TOPIC=${TOPIC_NAME},FRAMES_BUCKET=${FRAMES_BUCKET},FRAMES_PATH=${FRAMES_PATH},REPLAY_SPEED_MULTIPLIER=${REPLAY_SPEED_MULTIPLIER},AUTO_RESTART=${AUTO_RESTART}"

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
echo "URL:    $URL"
echo "Status: curl ${URL}/status"
echo "=================================================================="