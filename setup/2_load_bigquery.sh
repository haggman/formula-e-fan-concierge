#!/usr/bin/env bash
# Step 2/6 — Load BigQuery (fe_race10: 11 tables + 3 views)  (~4 min; telemetry + top-speed CTAS are the bulk)
# WHERE: Cloud Shell, repo root, after `source activate.sh`
# WHAT:  bash setup/2_load_bigquery.sh
# Idempotent: safe to rerun.
set -euo pipefail
cd "$(dirname "$0")/.."
source setup/_lib.sh
require_activation venv
banner "Step 2/6 — Load BigQuery (fe_race10: 11 tables + 3 views)"
python notebooks/bq_setup.py
