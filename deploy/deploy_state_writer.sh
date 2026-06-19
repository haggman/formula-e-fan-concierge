#!/usr/bin/env bash
# Deploy the State Writer service to Cloud Run + wire Pub/Sub push subscription.
#
# Idempotent: re-running updates the service and re-binds the subscription.
#
# Required env vars (set by sourcing activate.sh):
#   PROJECT_ID, REGION

set -euo pipefail

SERVICE_NAME="${SERVICE_NAME:-fe-state-writer}"
TOPIC_NAME="${TOPIC_NAME:-fe-telemetry}"
SUBSCRIPTION_NAME="${SUBSCRIPTION_NAME:-fe-state-writer-sub}"
SA_NAME="${SA_NAME:-fe-state-writer-sa}"

if [[ -z "${PROJECT_ID:-}" ]]; then
    echo "ERROR: PROJECT_ID env var required. Run: source activate.sh" >&2
    exit 1
fi
if [[ -z "${REGION:-}" ]]; then
    echo "ERROR: REGION env var required. Run: source activate.sh" >&2
    exit 1
fi

SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "=================================================================="
echo "Project: $PROJECT_ID"
echo "Region:  $REGION"
echo "Service: $SERVICE_NAME"
echo "Topic:   $TOPIC_NAME"
echo "Sub:     $SUBSCRIPTION_NAME"
echo "SA:      $SA_EMAIL"
echo "=================================================================="

# --- Enable APIs ---
echo ">>> Enabling APIs..."
gcloud services enable \
    run.googleapis.com \
    pubsub.googleapis.com \
    firestore.googleapis.com \
    cloudbuild.googleapis.com \
    --project="$PROJECT_ID"

# --- Wait for the Cloud Run admin API to actually serve ---
# On a brand-new project, `services enable` returns BEFORE the Run admin
# surface is queryable, so the first describe/deploy/IAM call can hit
# SERVICE_DISABLED and drop an interactive "enable and retry? (y/N)" prompt.
# Poll a cheap read until it stops failing (same propagation pattern as the
# IAM grants below) so the rest of the script runs unattended.
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
        --display-name="Formula E State Writer" \
        --project="$PROJECT_ID"
    echo "    created SA $SA_EMAIL"
else
    echo "    SA $SA_EMAIL exists"
fi

# --- IAM grants ---
# Firestore writes
echo ">>> Granting roles..."
for role in roles/datastore.user; do
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

# --- Topic must exist (the simulator creates it; this is just a safety net) ---
echo ">>> Ensuring Pub/Sub topic exists..."
if ! gcloud pubsub topics describe "$TOPIC_NAME" --project="$PROJECT_ID" >/dev/null 2>&1; then
    gcloud pubsub topics create "$TOPIC_NAME" --project="$PROJECT_ID"
    echo "    created topic $TOPIC_NAME (simulator will use this)"
else
    echo "    topic $TOPIC_NAME exists"
fi

# --- Deploy Cloud Run service ---
# --- Build the container image with Cloud Build ---
echo ">>> Building container image..."

# Use Artifact Registry repo named "fe-services" in our region.
# Idempotent: create if missing.
REPO_NAME="${REPO_NAME:-fe-services}"
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

IMAGE_TAG="$(date -u +%Y%m%d-%H%M%S)"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/state-writer:${IMAGE_TAG}"

CB_CONFIG="$(mktemp)"
cat > "$CB_CONFIG" <<EOF
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', '${IMAGE}', '-f', 'state_writer/Dockerfile', '.']
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
    --no-allow-unauthenticated \
    --cpu=1 \
    --memory=512Mi \
    --cpu-boost \
    --min-instances=0 \
    --max-instances=3 \
    --concurrency=10 \
    --timeout=60 \
    --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT_ID},RACE_ID=berlin_2024_r10" \
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

# --- Trigger Pub/Sub service agent provisioning ---
# The service agent (service-PROJECT_NUMBER@gcp-sa-pubsub.iam.gserviceaccount.com)
# is created on first Pub/Sub use in a project. Enabling the API alone doesn't
# materialize it. Force-create here so IAM bindings below can target it.
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
PUBSUB_SA="service-${PROJECT_NUMBER}@gcp-sa-pubsub.iam.gserviceaccount.com"

echo ">>> Provisioning Pub/Sub service agent..."
gcloud beta services identity create \
    --service=pubsub.googleapis.com \
    --project="$PROJECT_ID" >/dev/null
echo "    service agent: $PUBSUB_SA"

# --- Grant Pub/Sub SA permissions to invoke Cloud Run + use the SA token ---
# OIDC push auth: Pub/Sub mints a token AS the push-auth SA (fe-state-writer-sa),
# so THAT identity is what Cloud Run sees — it needs run.invoker. The Pub/Sub
# service agent only mints the token (tokenCreator below); it never invokes.
echo ">>> Granting push-auth SA invoker on Cloud Run service..."
gcloud run services add-iam-policy-binding "$SERVICE_NAME" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/run.invoker" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --quiet --verbosity=error

# Service agents materialize in IAM seconds-to-tens-of-seconds AFTER
# `services identity create` returns — and there's no existence probe for
# them (they live in a Google-owned tenant project), so the grant itself
# is the probe. Same 6x10s pattern as the project-level grants above.
granted=0
for attempt in 1 2 3 4 5 6; do
    if gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" \
        --member="serviceAccount:${PUBSUB_SA}" \
        --role="roles/iam.serviceAccountTokenCreator" \
        --project="$PROJECT_ID" \
        --quiet >/dev/null 2>&1; then
        granted=1
        break
    fi
    echo "    ...IAM can't see ${PUBSUB_SA} yet (service agent propagating) — retry ${attempt}/6 in 10s"
    sleep 10
done
if [[ "$granted" != "1" ]]; then
    echo "ERROR: failed to grant tokenCreator to ${PUBSUB_SA} after 6 attempts" >&2
    exit 1
fi
echo "    granted roles/iam.serviceAccountTokenCreator to ${PUBSUB_SA}"

# --- Create or update the push subscription ---
echo ">>> Configuring Pub/Sub push subscription..."
if gcloud pubsub subscriptions describe "$SUBSCRIPTION_NAME" --project="$PROJECT_ID" >/dev/null 2>&1; then
    gcloud pubsub subscriptions update "$SUBSCRIPTION_NAME" \
        --push-endpoint="$URL/" \
        --push-auth-service-account="$SA_EMAIL" \
        --project="$PROJECT_ID"
    echo "    updated subscription $SUBSCRIPTION_NAME"
else
    gcloud pubsub subscriptions create "$SUBSCRIPTION_NAME" \
        --topic="$TOPIC_NAME" \
        --push-endpoint="$URL/" \
        --push-auth-service-account="$SA_EMAIL" \
        --ack-deadline=60 \
        --message-retention-duration=10m \
        --project="$PROJECT_ID"
    echo "    created subscription $SUBSCRIPTION_NAME"
fi

echo ""
echo "=================================================================="
echo "Deployed!"
echo "URL: $URL"
echo ""
echo "Health check:  curl -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\" $URL/health"
echo "Status:        curl -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\" $URL/status"
echo "=================================================================="
echo ""
echo "Next step: deploy the simulator (companion repo) so it publishes to $TOPIC_NAME."
echo "Once the simulator is running, RaceState in Firestore will update at 1 Hz."
