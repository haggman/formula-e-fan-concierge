#!/usr/bin/env bash
# Step 4/6 — Firestore Native DB + composite indexes  (the long pole — indexes occasionally 10+ min)
# WHERE: Cloud Shell, repo root, after `source activate.sh`
# WHAT:  bash setup/4_setup_firestore.sh
# Idempotent: safe to rerun.
set -euo pipefail
cd "$(dirname "$0")/.."
source setup/_lib.sh
require_activation 
banner "Step 4/6 — Firestore Native DB + composite indexes"
bash deploy/setup_firestore.sh
