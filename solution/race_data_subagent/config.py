"""Race-data subagent configuration — race scope + the time bridge.

The time bridge MUST be identical to solution/commentator/config.py — both read
the same replay clock. Kept as a separate copy so each package is independently
deployable; a drift check belongs in the smoke test.
"""

RACE_ID = "berlin_2024_r10"

# Data range: this race + 10 seasons of career/results. The subagent may answer
# historical/career questions, bounded to the replay's current moment.
ALLOW_CAREER_HISTORY = True

# ----------------------------------------------------------------------------
# Time bridging — the spine of time-honesty. Keep in sync with commentator.
# Green flag: 2024-05-12T13:04:05.726Z.
# ----------------------------------------------------------------------------
RACE_START_EPOCH_NS = 1_715_519_045_726_000_000


def race_time_to_wall_ns(race_time_s: int) -> int:
    """Race-relative seconds → 2024 wall-clock ns. Use as through_time_ns (BQ)."""
    return RACE_START_EPOCH_NS + race_time_s * 1_000_000_000
