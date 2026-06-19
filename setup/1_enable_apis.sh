#!/usr/bin/env bash
# Step 1/6 — Enable Google Cloud APIs  (~1 min)
# WHERE: Cloud Shell, repo root, after `source activate.sh`
# WHAT:  bash setup/1_enable_apis.sh
# Idempotent: safe to rerun.
set -euo pipefail
cd "$(dirname "$0")/.."
source setup/_lib.sh
require_activation 
banner "Step 1/6 — Enable Google Cloud APIs"
bash deploy/enable_apis.sh
