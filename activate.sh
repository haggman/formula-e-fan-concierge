#!/usr/bin/env bash
# Activate the formula-e-race-engineer dev environment.
#
# Usage (must use 'source', not bash):
#     source activate.sh
#
# Idempotent: safe to source multiple times per shell session.

# --- Region ---
# Default to us-central1 (matches gs://class-demo bucket region).
# Override before sourcing if your lab assigns a different region:
#     export REGION=us-east1
#     source activate.sh
export REGION="${REGION:-us-central1}"

# --- Project ID ---
# Read from gcloud config (Qwiklabs sets this).
export PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
if [[ -z "$PROJECT_ID" ]]; then
    echo "ERROR: no project set. Run 'gcloud config set project YOUR_PROJECT'." >&2
    return 1 2>/dev/null || exit 1
fi

# --- Virtual environment ---
# Find the repo root (the directory containing this script's parent).
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${REPO_ROOT}/.venv"

if [[ ! -d "$VENV_DIR" ]]; then
    echo ">>> Creating virtual environment at $VENV_DIR"
    python3 -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

# --- Install / update requirements ---
# Check if requirements are satisfied. If not, install.
# We use a stamp file so we don't run pip on every source.
REQ_FILE="${REPO_ROOT}/requirements.txt"
STAMP_FILE="${VENV_DIR}/.req-stamp"

if [[ -f "$REQ_FILE" ]]; then
    if [[ ! -f "$STAMP_FILE" ]] || [[ "$REQ_FILE" -nt "$STAMP_FILE" ]]; then
        echo ">>> Installing requirements (requirements.txt is newer than venv stamp)"
        echo "    upgrading pip, wheel, setuptools..."
        pip install --upgrade pip wheel setuptools 2>&1 | grep -E "^(Collecting|Installing|Successfully|Requirement already)" || true
        echo ""
        echo "    installing project requirements..."
        pip install -r "$REQ_FILE" 2>&1 | grep -E "^(Collecting|Installing|Successfully|Requirement already|ERROR)" || true
        touch "$STAMP_FILE"
        echo ""
        echo "    installing project packages (editable)..."
        pip install -e "$REPO_ROOT" 2>&1 | grep -E "^(Obtaining|Installing|Successfully|ERROR)" || true
    fi
fi

# --- Vertex AI / ADK ---
export GOOGLE_GENAI_USE_VERTEXAI=1
export GOOGLE_CLOUD_PROJECT="$PROJECT_ID"
export GOOGLE_CLOUD_LOCATION="${GOOGLE_CLOUD_LOCATION:-global}"

# --- MCP Toolbox URL (auto-discovered from Cloud Run; bounded by timeout so
# a fresh project's first gcloud call can't silently hang the activation) ---
if [[ -z "${TOOLBOX_URL:-}" ]]; then
    echo ">>> Discovering TOOLBOX_URL (quick no-op if fe-toolbox isn't deployed yet)..."
    TOOLBOX_URL="$(timeout 10 gcloud run services describe fe-toolbox --region "$REGION" --format='value(status.url)' 2>/dev/null || true)"
fi
export TOOLBOX_URL

# --- Agent mode (chunk 13) ---
# local  = InMemoryRunner in-process (the dev path, default)
# engine = the deployed Agent Engine (set AGENT_MODE=engine before sourcing,
#          or per-run: AGENT_MODE=engine uvicorn frontend.main:app ...)
export AGENT_MODE="${AGENT_MODE:-local}"

# --- Agent package (the starter/solution seam) ---
# Which package the frontend and dev scripts load the agent from:
#   starter.race_engineer  = the student build (DEFAULT — you work here)
#   solution.race_engineer = the complete reference (the answer key)
# Instructors / demoing the reference:
#   export AGENT_PACKAGE=solution.race_engineer   (before sourcing, or per-run)
export AGENT_PACKAGE="${AGENT_PACKAGE:-starter.race_engineer}"

# Engine resource name — auto-loaded from the deploy script's record.
ENGINE_RESOURCE_FILE="${REPO_ROOT}/deploy/.engine_resource"
if [[ -z "${AGENT_ENGINE_RESOURCE:-}" && -f "$ENGINE_RESOURCE_FILE" ]]; then
    export AGENT_ENGINE_RESOURCE="$(tr -d '[:space:]' < "$ENGINE_RESOURCE_FILE")"
fi

# --- Status ---
echo ""
echo "=================================================================="
echo "  formula-e-race-engineer activated"
echo "=================================================================="
echo "  Project:    $PROJECT_ID"
echo "  Region:     $REGION"
echo "  Venv:       $VENV_DIR"
echo "  Python:     $(python3 --version)"
echo "  Agent mode: $AGENT_MODE"
echo "  Agent pkg:  $AGENT_PACKAGE"
if [[ -n "${AGENT_ENGINE_RESOURCE:-}" ]]; then
    echo "  Engine:     $AGENT_ENGINE_RESOURCE"
else
    echo "  Engine:     (none — deploy/deploy_agent_engine.sh records one)"
fi
echo "=================================================================="
echo ""
echo "To deactivate: 'deactivate'"
echo "To re-install requirements: 'rm ${STAMP_FILE} && source activate.sh'"
