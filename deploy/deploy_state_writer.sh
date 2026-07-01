#!/usr/bin/env bash
# Deploy the State Writer as a Cloud Run WORKER POOL that PULLs from Pub/Sub and
# writes RaceState + Events to Firestore. (Converted from the old FastAPI push
# service — see spec/state_writer_worker_pool.md.)
#
# Why a worker pool: a Pub/Sub-pull consumer has no request surface, so it wants
# a long-running worker, not an HTTP service. Pull also drops all the push-auth
# plumbing (OIDC SA + run.invoker + tokenCreator on the Pub/Sub service agent).
#
# Idempotent: re-running updates the pool and re-configures the subscription.
#
# NOTE: Cloud Run worker pools were GA-ing around this build. If `gcloud run
# worker-pools deploy` or its flags differ in your gcloud, adjust the DEPLOY
# block below — the rest (image build, pull subscription, IAM) is standard.
#
# Required env vars (set by sourcing activate.sh): PROJECT_ID, REGION

set -euo pipefail

POOL_NAME="${SERVICE_NAME:-fe-state-writer}"          # worker pool name (kept the old name)
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
echo "Project:   $PROJECT_ID"
echo "Region:    $REGION"
echo "Pool:      $POOL_NAME   (Cloud Run worker pool, Pub/Sub pull)"
echo "Topic:     $TOPIC_NAME"
echo "Sub:       $SUBSCRIPTION_NAME   (pull)"
echo "SA:        $SA_EMAIL"
echo "=================================================================="

# --- Enable APIs ---
echo ">>> Enabling APIs..."
gcloud services enable \
    run.googleapis.com \
    pubsub.googleapis.com \
    firestore.googleapis.com \
    cloudbuild.googleapis.com \
    --project="$PROJECT_ID"

# --- Wait for the Cloud Run admin API to actually serve (fresh-project race) ---
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

# --- IAM grants: Firestore write + Pub/Sub pull ---
# (No run.invoker / tokenCreator / service-agent — those were push-auth only.)
echo ">>> Granting roles..."
for role in roles/datastore.user roles/pubsub.subscriber; do
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

# --- Topic must exist (the simulator creates it; safety net) ---
echo ">>> Ensuring Pub/Sub topic exists..."
if ! gcloud pubsub topics describe "$TOPIC_NAME" --project="$PROJECT_ID" >/dev/null 2>&1; then
    gcloud pubsub topics create "$TOPIC_NAME" --project="$PROJECT_ID"
    echo "    created topic $TOPIC_NAME (simulator will use this)"
else
    echo "    topic $TOPIC_NAME exists"
fi

# --- Create/convert the PULL subscription ---
# A pull subscription has no push endpoint. If a push subscription from the old
# deploy exists, --clear-push-config converts it to pull in place.
echo ">>> Configuring Pub/Sub PULL subscription..."
if gcloud pubsub subscriptions describe "$SUBSCRIPTION_NAME" --project="$PROJECT_ID" >/dev/null 2>&1; then
    gcloud pubsub subscriptions update "$SUBSCRIPTION_NAME" \
        --clear-push-config \
        --ack-deadline=60 \
        --project="$PROJECT_ID"
    echo "    updated subscription $SUBSCRIPTION_NAME to pull"
else
    gcloud pubsub subscriptions create "$SUBSCRIPTION_NAME" \
        --topic="$TOPIC_NAME" \
        --ack-deadline=60 \
        --message-retention-duration=10m \
        --project="$PROJECT_ID"
    echo "    created pull subscription $SUBSCRIPTION_NAME"
fi

# --- Build the container image with Cloud Build ---
echo ">>> Building container image..."
REPO_NAME="${REPO_NAME:-fe-services}"
if ! gcloud artifacts repositories describe "$REPO_NAME" \
        --location="$REGION" --project="$PROJECT_ID" >/dev/null 2>&1; then
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
gcloud builds submit "$REPO_ROOT" --config="$CB_CONFIG" --project="$PROJECT_ID"
rm -f "$CB_CONFIG"
echo "    built and pushed: $IMAGE"

# --- Deploy the worker pool ---
# 1 Hz frames, single race → size 1 is plenty (idempotency makes scaling safe
# but unnecessary). No URL, no port, no concurrency/timeout — it's not a service.
echo ">>> Deploying Cloud Run worker pool..."
gcloud run worker-pools deploy "$POOL_NAME" \
    --image="$IMAGE" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --service-account="$SA_EMAIL" \
    --cpu=1 \
    --memory=512Mi \
    --min-instances=1 \
    --max-instances=1 \
    --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT_ID},SUBSCRIPTION_NAME=${SUBSCRIPTION_NAME}" \
    --quiet

echo ""
echo "=================================================================="
echo "Deployed worker pool: $POOL_NAME"
echo ""
echo "It pulls $SUBSCRIPTION_NAME and writes race_states/ + race_events/ in Firestore."
echo "Logs:    gcloud run worker-pools logs read $POOL_NAME --region $REGION"
echo "Status:  gcloud run worker-pools describe $POOL_NAME --region $REGION"
echo "=================================================================="
echo ""
echo "Next: run the simulator so it publishes to $TOPIC_NAME. RaceState in"
echo "Firestore then updates at 1 Hz (verify with: python setup/verify_checks.py"
echo "or the SIM bar in the frontend)."
