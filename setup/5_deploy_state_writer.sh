#!/usr/bin/env bash
# Step 5/6 — Deploy the State Writer (Pub/Sub push -> Firestore)  (~4 min Cloud Build)
# WHERE: Cloud Shell, repo root, after `source activate.sh`
# WHAT:  bash setup/5_deploy_state_writer.sh
# Idempotent: safe to rerun.
set -euo pipefail
cd "$(dirname "$0")/.."
source setup/_lib.sh
require_activation 
banner "Step 5/6 — Deploy the State Writer (Pub/Sub push -> Firestore)"
bash deploy/deploy_state_writer.sh
