#!/usr/bin/env bash
# Deploy the race engineer to Agent Engine on Agent Platform (chunk 12).
#
# WHERE: Cloud Shell (Qwiklabs student account), repo root, venv active
# WHAT:  bash deploy/deploy_agent_engine.sh
#
# Stages the self-contained app (build_engine_app.py), grants the Agent
# Engine service agent Firestore read access, deploys, and saves the
# resource name to deploy/.engine_resource for the frontend/smoke test.
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-us-central1}"
DISPLAY_NAME="fe-race-engineer"

echo "== Staging the self-contained engine app =="
python3 deploy/build_engine_app.py

echo "== Deploying to Agent Engine on Agent Platform =="
echo "   The create step is a blocking operation with NO progress output —"
echo "   typically 5-10 minutes while the runtime builds your requirements."
echo "   To watch build logs from a second terminal:"
echo "     gcloud logging read 'resource.type=\"aiplatform.googleapis.com/ReasoningEngine\"' \\"
echo "         --freshness=15m --order=asc --format='value(textPayload)' --project=$PROJECT_ID"
EXISTING_ID=""
if [[ -f deploy/.engine_resource ]]; then
    EXISTING_ID=$(sed 's|.*/reasoningEngines/||' deploy/.engine_resource)
    echo "Updating existing engine: ${EXISTING_ID}"
fi

# Finding #16: the engine create is just one more flaky GCP call. #13 left
# it un-retried on the assumption the 5-minute create was reliable; on
# 2026-06-15 it returned a transient code 13 (INTERNAL) and a clean re-run
# (no code change) succeeded. Two traps make this one different from the
# 6x10s IAM loops:
#   1. `adk deploy` SWALLOWS the API error and still exits 0 — so success is
#      gated on parsing a reasoningEngines name, never on $?. (That swallow
#      is why a failed create used to fall through to the misleading
#      "Could not parse the resource name" copy-it-yourself message.)
#   2. The create is EXPENSIVE (5-10 min on success) — so this retries few
#      times with a long pause, NOT 6x10s, and ONLY on a transient
#      signature. A deterministic failure (bad requirements / INVALID_
#      ARGUMENT / quota) fails fast so we don't burn ~30 min on a build that
#      can never pass. Tunable via ENGINE_DEPLOY_ATTEMPTS / _DELAY.
ENGINE_DEPLOY_ATTEMPTS="${ENGINE_DEPLOY_ATTEMPTS:-3}"
ENGINE_DEPLOY_DELAY="${ENGINE_DEPLOY_DELAY:-30}"
RESOURCE=""
for attempt in $(seq 1 "$ENGINE_DEPLOY_ATTEMPTS"); do
    # 2>&1 so the API error text lands in the log for classification below.
    adk deploy agent_engine \
        --project="$PROJECT_ID" \
        --region="$REGION" \
        --display_name="$DISPLAY_NAME" \
        ${EXISTING_ID:+--agent_engine_id="$EXISTING_ID"} \
        build/engine_app 2>&1 | tee /tmp/engine_deploy.log

    RESOURCE=$(grep -oE 'projects/[^ ]+/reasoningEngines/[0-9]+' /tmp/engine_deploy.log | tail -1 || true)
    [[ -n "$RESOURCE" ]] && break   # got a resource name => the create stuck

    # No resource name => the create failed. Retry only if it looks transient.
    if grep -qiE "'code': ?(13|14|4)|INTERNAL|UNAVAILABLE|DEADLINE_EXCEEDED|try again|temporar|backend error|503|500" /tmp/engine_deploy.log; then
        if [[ "$attempt" -lt "$ENGINE_DEPLOY_ATTEMPTS" ]]; then
            echo "    ...engine create returned a transient error (no resource name) — retry ${attempt}/${ENGINE_DEPLOY_ATTEMPTS} in ${ENGINE_DEPLOY_DELAY}s" >&2
            sleep "$ENGINE_DEPLOY_DELAY"
            continue
        fi
        echo "ERROR: engine create failed with a transient error after ${ENGINE_DEPLOY_ATTEMPTS} attempts." >&2
    else
        echo "ERROR: engine create failed and the error does NOT look transient — not retrying." >&2
        echo "       This is usually a requirements/build problem (bad dependency, INVALID_ARGUMENT, quota)." >&2
    fi
    echo "       Inspect /tmp/engine_deploy.log, and the build logs:" >&2
    echo "         gcloud logging read 'resource.type=\"aiplatform.googleapis.com/ReasoningEngine\"' --freshness=15m --order=asc --format='value(textPayload)' --project=$PROJECT_ID" >&2
    exit 1
done
if [[ -n "$RESOURCE" ]]; then
    echo "$RESOURCE" > deploy/.engine_resource
    echo "== Saved resource name to deploy/.engine_resource =="
    echo "$RESOURCE"

    echo "== Granting the Agent Engine service agent Firestore access =="
    # The service agent is created by the first deploy; the multi-minute
    # engine create has so far been an accidental propagation wait, but
    # that's the same optimism Findings #8/#12/#13 punished — retry like
    # every other grant (service agents have no existence probe; the
    # grant IS the probe).
    PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
    ENGINE_SA="service-${PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"
    granted=0
    for attempt in 1 2 3 4 5 6; do
        if gcloud projects add-iam-policy-binding "$PROJECT_ID" \
            --member="serviceAccount:${ENGINE_SA}" \
            --role="roles/datastore.user" \
            --condition=None --quiet >/dev/null 2>&1; then
            granted=1
            break
        fi
        echo "    ...IAM can't see ${ENGINE_SA} yet (service agent propagating) — retry ${attempt}/6 in 10s"
        sleep 10
    done
    if [[ "$granted" != "1" ]]; then
        echo "ERROR: failed to grant datastore.user to ${ENGINE_SA} after 6 attempts" >&2
        exit 1
    fi
    echo "Granted roles/datastore.user to ${ENGINE_SA}"
else
    echo "!! Could not parse the resource name from the deploy output."
    echo "   Copy the 'reasoningEngines' name from above into deploy/.engine_resource manually."
fi