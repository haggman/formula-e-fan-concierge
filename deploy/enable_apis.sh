#!/usr/bin/env bash
# Enable every API the race engineer stack needs. Idempotent — run any time.
# This is lab step zero: everything else assumes these are on.
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
echo "Enabling APIs on project: ${PROJECT_ID}"

# --- Core stack (strict: any failure here IS fatal — nothing works without
# these). The second line is the Agent Engine documented set (Vertex AI,
# Storage, Logging, Monitoring, Trace, Telemetry, Resource Manager) plus
# Compute, which the console expects on.
gcloud services enable \
    run.googleapis.com \
    pubsub.googleapis.com \
    firestore.googleapis.com \
    bigquery.googleapis.com \
    aiplatform.googleapis.com \
    texttospeech.googleapis.com \
    speech.googleapis.com \
    cloudbuild.googleapis.com \
    artifactregistry.googleapis.com \
    storage.googleapis.com \
    logging.googleapis.com \
    monitoring.googleapis.com \
    cloudtrace.googleapis.com \
    telemetry.googleapis.com \
    cloudresourcemanager.googleapis.com \
    compute.googleapis.com \
    --project "${PROJECT_ID}"

# --- Agent Engine console extras (tolerant: enabled one-by-one, WARN on
# failure). The 2026 Agent Engine console's "Enable required APIs" dialog
# wants all of these before it will show deployed engines. Several are
# brand-new surfaces whose service IDs may shift (iamconnectors is a
# best-guess — the console name "IAM Connectors API" has no documented ID
# yet), and lab projects can have org-policy blocks on some (e.g. Security
# Command Center) — none of that is worth killing setup/all.sh over. The
# engine itself deploys fine without them; this is about the console UX.
CONSOLE_EXTRAS=(
    agentregistry.googleapis.com      # Agent Registry API
    apphub.googleapis.com             # App Hub API
    apptopology.googleapis.com        # App Topology API
    cloudapiregistry.googleapis.com   # Cloud API Registry API
    dataform.googleapis.com           # Dataform API
    iam.googleapis.com                # IAM API
    iamconnectors.googleapis.com      # IAM Connectors API (unverified ID)
    iap.googleapis.com                # Cloud Identity-Aware Proxy API
    modelarmor.googleapis.com         # Model Armor API
    networksecurity.googleapis.com    # Network Security API
    networkservices.googleapis.com    # Network Services API
    notebooks.googleapis.com          # Notebooks API
    observability.googleapis.com      # Observability API
    saasservicemgmt.googleapis.com    # App Lifecycle Manager API
    securitycenter.googleapis.com     # Security Command Center API
)
echo ""
echo "Enabling Agent Engine console extras (failures here are WARNs, not fatal):"
for api in "${CONSOLE_EXTRAS[@]}"; do
    if gcloud services enable "$api" --project "${PROJECT_ID}" --quiet >/dev/null 2>&1; then
        echo "    enabled  $api"
    else
        echo "    WARN: could not enable $api — console may still prompt for it; everything else proceeds" >&2
    fi
done

echo ""
echo "Done. Current AI/speech/data services:"
gcloud services list --enabled --project "${PROJECT_ID}" \
    --filter="config.name:(aiplatform OR texttospeech OR speech OR bigquery OR firestore OR pubsub OR run)" \
    --format="value(config.name)"
