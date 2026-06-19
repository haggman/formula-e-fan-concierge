#!/usr/bin/env bash
# Set up Firestore Native mode database for the race engineer agent.
#
# Idempotent: safe to re-run. Skips creation if database already exists.
#
# Index builds are submitted ASYNC and this script returns immediately:
# nothing else in setup depends on the indexes (only event QUERIES do, and
# those happen minutes later when an agent runs). setup/verify.sh confirms
# readiness as its final check, with a bounded wait.
#
# (The previous version polled gcloud for index state here. The poll's
# --filter="collectionGroup=..." key doesn't resolve in current gcloud,
# so READY was never detected and every run burned the full 15-minute
# timeout. Readiness checking now lives in setup/verify_checks.py, via the
# Firestore admin API — structured data, no text scraping.)
#
# Required env vars (set by sourcing activate.sh):
#   PROJECT_ID, REGION

set -euo pipefail

if [[ -z "${PROJECT_ID:-}" ]]; then
    echo "ERROR: PROJECT_ID env var required. Run: source activate.sh" >&2
    exit 1
fi
if [[ -z "${REGION:-}" ]]; then
    echo "ERROR: REGION env var required. Run: source activate.sh" >&2
    exit 1
fi

# Firestore uses a "location" that maps to either a region or a multi-region.
# For single-region: same string as Cloud Run region (e.g. "us-central1").
FIRESTORE_LOCATION="${FIRESTORE_LOCATION:-${REGION}}"
DATABASE_ID="${FIRESTORE_DATABASE_ID:-(default)}"

echo "=================================================================="
echo "Project:  $PROJECT_ID"
echo "Location: $FIRESTORE_LOCATION"
echo "Database: $DATABASE_ID"
echo "=================================================================="

# --- Enable API ---
echo ">>> Enabling Firestore API..."
gcloud services enable firestore.googleapis.com --project="$PROJECT_ID"

# --- Create the (default) Native-mode database if missing ---
echo ">>> Checking for existing database..."
if gcloud firestore databases describe \
        --database="$DATABASE_ID" \
        --project="$PROJECT_ID" >/dev/null 2>&1; then
    EXISTING_TYPE="$(gcloud firestore databases describe \
        --database="$DATABASE_ID" \
        --project="$PROJECT_ID" \
        --format='value(type)')"
    EXISTING_LOC="$(gcloud firestore databases describe \
        --database="$DATABASE_ID" \
        --project="$PROJECT_ID" \
        --format='value(locationId)')"
    echo "    Database '$DATABASE_ID' already exists (type=$EXISTING_TYPE, location=$EXISTING_LOC)"
    if [[ "$EXISTING_TYPE" != "FIRESTORE_NATIVE" ]]; then
        echo "    WARN: existing DB is not Native mode. Agent code assumes Native mode."
    fi
else
    echo ">>> Creating Native-mode database in $FIRESTORE_LOCATION..."
    gcloud firestore databases create \
        --database="$DATABASE_ID" \
        --location="$FIRESTORE_LOCATION" \
        --type=firestore-native \
        --project="$PROJECT_ID"
    echo "    created"
fi

# --- Composite indexes (submitted async; verify.sh checks readiness) ---
echo ""
echo ">>> Submitting composite index creates (async)..."

create_index() {
    local desc="$1"; shift
    if out="$(gcloud firestore indexes composite create \
        --database="$DATABASE_ID" \
        --project="$PROJECT_ID" \
        --collection-group=race_events \
        --query-scope=COLLECTION \
        --async \
        "$@" 2>&1)"; then
        echo "    ⏳ $desc — submitted"
    else
        if echo "$out" | grep -q "already exists"; then
            echo "    ✓ $desc — already exists"
        else
            echo "    ✗ $desc — ERROR: $out" >&2
            return 1
        fi
    fi
}

create_index "race_id + race_time_s (desc)" \
    --field-config=field-path=race_id,order=ascending \
    --field-config=field-path=race_time_s,order=descending

create_index "race_id + event_type + race_time_s (desc)" \
    --field-config=field-path=race_id,order=ascending \
    --field-config=field-path=event_type,order=ascending \
    --field-config=field-path=race_time_s,order=descending

create_index "race_id + car_number + race_time_s (desc)" \
    --field-config=field-path=race_id,order=ascending \
    --field-config=field-path=car_number,order=ascending \
    --field-config=field-path=race_time_s,order=descending

echo ""
echo ">>> Done. Index builds run in Firestore's background (typically 1-10"
echo "    minutes, occasionally longer). Nothing else in setup waits on them;"
echo "    setup/verify.sh confirms readiness as its final check."
echo "    Watch manually any time:"
echo "      gcloud firestore indexes composite list --database='$DATABASE_ID' \\"
echo "          --project=$PROJECT_ID --format='table(name.basename(),state)'"
