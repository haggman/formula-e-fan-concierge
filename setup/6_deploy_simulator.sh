#!/usr/bin/env bash
# Step 6/6 — Deploy the simulator (publishes the moment it is up)  (~3 min)
# WHERE: Cloud Shell, repo root, after `source activate.sh`
# WHAT:  bash setup/6_deploy_simulator.sh
# Idempotent: safe to rerun.
set -euo pipefail
cd "$(dirname "$0")/.."
source setup/_lib.sh
require_activation 
banner "Step 6/6 — Deploy the simulator (publishes the moment it is up)"
# Deployed LAST on purpose: the State Writer subscription (step 5) must be
# listening before frames start flowing, or the first minutes of replay
# silently evaporate (Pub/Sub retains undeliverable pushes ~10 min).
( cd simulator && bash deploy.sh )
