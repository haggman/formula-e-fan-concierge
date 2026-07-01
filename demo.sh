#!/usr/bin/env bash
# demo.sh — launch the Race-Day Companion with nothing to remember.
#
# WHERE: Cloud Shell (any directory — the script cd's to the repo itself)
# WHAT:  bash demo.sh                  # YOUR commentator (the starter package)
#        RUN_SOLUTION=1 bash demo.sh   # the finished reference commentator
#
# Stage knobs (opt-in — a plain relaunch never touches the running race):
#        RUN_SOLUTION=1 FRESH=1 SPEED=2 bash demo.sh   # audience demo: fresh race from the grid, 2x
#        RUN_SOLUTION=1 FRESH=1 SPEED=5 bash demo.sh   # rehearsal: the race compressed
#
# Re-sources activate.sh and re-derives SIM_URL on every launch, so a fresh tab
# or a recycled Cloud Shell session can never leave the page sim-less.

set -eo pipefail
cd "$(dirname "$0")"

source activate.sh   # sets venv, PROJECT_ID, REGION, AGENT_PACKAGE (default: starter.commentator)

if [[ "${RUN_SOLUTION:-0}" == "1" ]]; then
    export AGENT_PACKAGE=solution.commentator
    echo "demo.sh: RUN_SOLUTION=1 — the finished reference commentator"
fi

export SIM_URL="${SIM_URL:-$(gcloud run services describe fe-simulator --region "$REGION" --format='value(status.url)' 2>/dev/null)}"
if [[ -z "$SIM_URL" ]]; then
    echo "ERROR: could not derive SIM_URL — is fe-simulator deployed in ${REGION}?" >&2
    exit 1
fi

# fe-simulator is private; the stage-control curls carry an identity token.
SIM_AUTH=(-H "Authorization: Bearer $(gcloud auth print-identity-token)")

if [[ -n "${SPEED:-}" ]]; then
    curl -s "${SIM_AUTH[@]}" -X POST "$SIM_URL/speed" -H 'Content-Type: application/json' \
        -d "{\"multiplier\": ${SPEED}}" >/dev/null && echo "demo.sh: sim speed -> ${SPEED}x"
fi
if [[ "${FRESH:-0}" == "1" ]]; then
    curl -s "${SIM_AUTH[@]}" -X POST "$SIM_URL/restart" >/dev/null
    curl -s "${SIM_AUTH[@]}" -X POST "$SIM_URL/resume"  >/dev/null
    echo "demo.sh: race restarted from the grid, running"
fi

echo "demo.sh: AGENT_PACKAGE=${AGENT_PACKAGE:-<activate.sh default>}"
echo "demo.sh: SIM_URL=${SIM_URL}"
echo "demo.sh: open Web Preview on port 8080"
exec uvicorn frontend.main:app --host 0.0.0.0 --port 8080
