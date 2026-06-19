#!/usr/bin/env bash
# setup/all.sh — the one-command data-plane setup: steps 1-6, then verify.
# WHERE: Cloud Shell, repo root, after `source activate.sh`
# WHAT:  bash setup/all.sh
#
# Wall clock: budget 20 minutes, ~10 typical on a fresh project (Firestore
# index builds are the one variable). Idempotent: safe to rerun after a
# failure — completed steps fast-forward.
#
# What this does NOT do: deploy Agent Engine or the Cloud Run frontend.
# Those are the optional instructor extras: bash setup/7_deploy_cloud.sh
set -euo pipefail
cd "$(dirname "$0")/.."
source setup/_lib.sh
require_activation venv

T0=$SECONDS
STEPS=(1_enable_apis 2_load_bigquery 3_deploy_toolbox
       4_setup_firestore 5_deploy_state_writer 6_deploy_simulator)

for step in "${STEPS[@]}"; do
    s0=$SECONDS
    bash "setup/${step}.sh"
    echo ""
    echo ">>> ${step} completed in $(( SECONDS - s0 ))s"
done

bash setup/verify.sh

echo ""
echo "=================================================================="
printf "  setup/all.sh complete in %dm %02ds\n" $(( (SECONDS - T0) / 60 )) $(( (SECONDS - T0) % 60 ))
echo "  Next: source activate.sh    (picks up TOOLBOX_URL in this shell)"
echo "        then build your agent — see STUDENT_GUIDE.md"
echo "=================================================================="
