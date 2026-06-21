#!/usr/bin/env bash
# Step 7 — Deploy the race-data subagent to Cloud Run (race-data-subagent)
# WHERE: Cloud Shell, repo root, after `source activate.sh` AND `bash setup/all.sh`
# WHAT:  bash setup/7_deploy_subagent.sh
#
# This lab's deploy: the ADK race-data subagent that CX calls (the agent IS the
# service — POST /ask_race_data). Needs the data layer (steps 1-6) up first so
# LLM mode has Firestore "now" + fe-toolbox to read. Idempotent: safe to rerun.
#
# Defaults to DETERMINISTIC=1 (first-light wire test — no LLM/creds needed); flip
# to the real agent with:  DETERMINISTIC=0 bash setup/7_deploy_subagent.sh
# Deploy the student build with:  SUBAGENT_PACKAGE=starter.race_data_subagent ...
#
# Full deploy + live-verification steps: deploy/RUNBOOK_race_data_subagent.md
# (NOTE: the Agent-Engine + frontend "push to cloud" step is a LATER lab —
#  setup/8_deploy_cloud.sh — not used here.)
set -euo pipefail
cd "$(dirname "$0")/.."
source setup/_lib.sh
require_activation
banner "Step 7 — Deploy the race-data subagent to Cloud Run (race-data-subagent)"
bash deploy/deploy_race_data_subagent.sh
echo ""
echo "Verify + wire CX: see deploy/RUNBOOK_race_data_subagent.md"
