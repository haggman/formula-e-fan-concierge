#!/usr/bin/env bash
# Deploy MCP Toolbox to Cloud Run.
# Idempotent. Open auth for chunk 4 — locked down in chunk 13.

set -euo pipefail

if [[ -z "${REGION:-}" ]]; then
    echo "ERROR: REGION env var required. Run: source activate.sh" >&2
    exit 1
fi
SERVICE_NAME="${SERVICE_NAME:-fe-toolbox}"
SA_NAME="${SA_NAME:-fe-toolbox-sa}"
TOOLBOX_IMAGE="${TOOLBOX_IMAGE:-us-central1-docker.pkg.dev/database-toolbox/toolbox/toolbox:1.3.0}"

PROJECT_ID="$(gcloud config get-value project 2>/dev/null)"
if [[ -z "$PROJECT_ID" ]]; then
    echo "ERROR: no project set." >&2
    exit 1
fi

SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
STAGING_BUCKET="${STAGING_BUCKET:-${PROJECT_ID}-fe-toolbox}"

echo "=================================================================="
echo "Project: $PROJECT_ID"
echo "Region:  $REGION"
echo "Service: $SERVICE_NAME"
echo "SA:      $SA_EMAIL"
echo "Image:   $TOOLBOX_IMAGE"
echo "=================================================================="

echo ">>> Enabling APIs..."
gcloud services enable \
    run.googleapis.com \
    bigquery.googleapis.com \
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

echo ">>> Ensuring service account exists..."
if ! gcloud iam service-accounts describe "$SA_EMAIL" --project="$PROJECT_ID" >/dev/null 2>&1; then
    gcloud iam service-accounts create "$SA_NAME" \
        --display-name="Formula E MCP Toolbox" \
        --project="$PROJECT_ID"
    echo "    created SA $SA_EMAIL"
else
    echo "    SA $SA_EMAIL exists"
fi

echo ">>> Granting BigQuery roles..."
for role in roles/bigquery.dataViewer roles/bigquery.jobUser; do
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

TOOLS_YAML_PATH="$(cd "$(dirname "$0")/.." && pwd)/toolbox/tools.yaml"
if [[ ! -f "$TOOLS_YAML_PATH" ]]; then
    echo "ERROR: tools.yaml not found at $TOOLS_YAML_PATH" >&2
    exit 1
fi

echo ">>> Ensuring staging bucket gs://${STAGING_BUCKET}..."
if ! gcloud storage buckets describe "gs://${STAGING_BUCKET}" --project="$PROJECT_ID" >/dev/null 2>&1; then
    gcloud storage buckets create "gs://${STAGING_BUCKET}" \
        --project="$PROJECT_ID" \
        --location="$REGION" \
        --uniform-bucket-level-access
    echo "    created"
else
    echo "    exists"
fi

gcloud storage buckets add-iam-policy-binding "gs://${STAGING_BUCKET}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/storage.objectViewer" >/dev/null

gcloud storage cp "$TOOLS_YAML_PATH" "gs://${STAGING_BUCKET}/tools.yaml" --quiet
echo "    uploaded tools.yaml"

echo ">>> Deploying Cloud Run service..."
gcloud run deploy "$SERVICE_NAME" \
    --image="$TOOLBOX_IMAGE" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --service-account="$SA_EMAIL" \
    --allow-unauthenticated \
    --port=5000 \
    --cpu=1 \
    --memory=512Mi \
    --cpu-boost \
    --min-instances=1 \
    --max-instances=3 \
    --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT_ID}" \
    --args="--config=/tools/tools.yaml,--address=0.0.0.0,--port=5000" \
    --add-volume="name=tools-vol,type=cloud-storage,bucket=${STAGING_BUCKET}" \
    --add-volume-mount="volume=tools-vol,mount-path=/tools" \
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
echo "URL: $URL"
echo "=================================================================="
echo ""
echo "Export for the next chunks:"
echo "  export TOOLBOX_URL=${URL}"
echo ""
echo "Note: min-instances=1 keeps one container warm always."
echo "      Costs ~\$5-10/month. Run 'gcloud run services delete fe-toolbox --region us-central1' when done."