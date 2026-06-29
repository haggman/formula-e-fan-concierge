# ============================================================================
# GIVEN INFRASTRUCTURE — you do NOT need to edit or read this file in depth.
# It is the same field-wide tooling the reference uses. Your build is in
# prompts.py (the persona) and agent.py (wiring). See README.md.
# ============================================================================
"""Commentator configuration — race scope, AM constants, the time bridge.

Re-aimed from Ch2's race_engineer/config.py: the "our car #13" identity is GONE.
The commentator is a field-wide broadcaster; the only per-fan notion is the
*selected car*, which arrives at runtime via the websocket (not a constant here).
"""

# Race scope
RACE_ID = "berlin_2024_r10"

# Attack Mode constants (R10)
AM_TOTAL_BUDGET_S = 240
AM_SCENARIOS = {
    1: "short-first (60s + 180s)",
    2: "even (120s + 120s)",
    3: "long-first (180s + 60s)",
}

# ----------------------------------------------------------------------------
# Time bridging: race time ↔ the 2024 race's wall clock
# ----------------------------------------------------------------------------
# Kept verbatim from Ch2. The commentator doesn't query BigQuery, but the
# bridge is the canonical clock for the whole repo and the race-data subagent
# depends on the identical constant — keep them in sync.
#
# Green flag: 2024-05-12T13:04:05.726Z. Exact integer, no float arithmetic.
RACE_START_EPOCH_NS = 1_715_519_045_726_000_000


def race_time_to_wall_ns(race_time_s: int) -> int:
    """Convert race-relative seconds to the 2024 race's wall-clock ns."""
    return RACE_START_EPOCH_NS + race_time_s * 1_000_000_000
