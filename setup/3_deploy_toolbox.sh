#!/usr/bin/env bash
# Step 3/6 — Deploy MCP Toolbox to Cloud Run (fe-toolbox)  (~3 min)
# WHERE: Cloud Shell, repo root, after `source activate.sh`
# WHAT:  bash setup/3_deploy_toolbox.sh
# Idempotent: safe to rerun.
set -euo pipefail
cd "$(dirname "$0")/.."
source setup/_lib.sh
require_activation 
banner "Step 3/6 — Deploy MCP Toolbox to Cloud Run (fe-toolbox)"
bash deploy/deploy_toolbox.sh
echo ""
echo "Note: re-run \"source activate.sh\" in dev shells so TOOLBOX_URL is picked up."
