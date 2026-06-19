#!/usr/bin/env bash
# OPTIONAL instructor step — push the brain and the UI into GCP.  (~15-20 min)
# WHERE: Cloud Shell, repo root, after `source activate.sh`, AFTER setup/all.sh
# WHAT:  bash setup/7_deploy_cloud.sh
#
# Deploys:
#   1. The agent to Vertex AI Agent Engine (Agent Runtime). The create step
#      is a BLOCKING operation with no progress output — typically 5-10
#      minutes of silence. The deploy script prints a gcloud logging
#      one-liner for watching build logs from a second terminal.
#   2. The pit-wall frontend to Cloud Run (public demo URL), wired to the
#      engine (AGENT_MODE=engine). The container's package default is
#      solution.race_engineer — the deployed demo always runs the reference,
#      regardless of your shell's AGENT_PACKAGE.
#
# Skipping this is fine: the full product runs locally (uvicorn + Web
# Preview) against the data plane from setup/all.sh. This step exists for
# the opening demo's public URL and the "how production does it" story.
set -euo pipefail
cd "$(dirname "$0")/.."
source setup/_lib.sh
require_activation venv

# The engine build bakes TOOLBOX_URL + PROJECT_ID into its .env — make sure
# the URL is discovered even if this shell was activated before step 3 ran.
export TOOLBOX_URL="${TOOLBOX_URL:-$(gcloud run services describe fe-toolbox --region "$REGION" --format='value(status.url)' 2>/dev/null || true)}"
if [[ -z "$TOOLBOX_URL" ]]; then
    echo "ERROR: fe-toolbox not found — run setup/all.sh (or setup/3_deploy_toolbox.sh) first." >&2
    exit 1
fi

banner "Optional 1/2 — Agent to Agent Engine (silent 5-10 min create)"
bash deploy/deploy_agent_engine.sh

banner "Optional 2/2 — Pit-wall frontend to Cloud Run"
bash deploy/deploy_frontend.sh

echo ""
echo "Demo smoke test:  python scripts/engine_smoke.py"
