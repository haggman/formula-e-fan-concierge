#!/usr/bin/env bash
# Green-light check — verifies the whole deployed data plane.  (~1 min)
# WHERE: Cloud Shell, repo root, after `source activate.sh`
# WHAT:  bash setup/verify.sh
# Run any time; setup/all.sh runs it automatically as its last step.
set -euo pipefail
cd "$(dirname "$0")/.."
source setup/_lib.sh
require_activation venv
banner "Verify — green-light check"

# Discover service URLs (no-ops if already exported). Bounded + non-interactive
# so a project where setup hasn't run can't silently hang here: with the Cloud
# Run API not yet enabled, gcloud otherwise prints "enable this API? (y/N)" to
# the suppressed stderr and blocks on stdin forever. </dev/null refuses the
# prompt and `timeout 10` is the backstop, so this fails fast to an empty URL
# and checks 1 + 5 report the miss immediately. (Same guard activate.sh uses.)
export SIM_URL="${SIM_URL:-$(timeout 10 gcloud run services describe fe-simulator --region "$REGION" --format='value(status.url)' </dev/null 2>/dev/null || true)}"
export TOOLBOX_URL="${TOOLBOX_URL:-$(timeout 10 gcloud run services describe fe-toolbox --region "$REGION" --format='value(status.url)' </dev/null 2>/dev/null || true)}"

python setup/verify_checks.py
