"""Subagent config — STARTER. RACE_ID + the time bridge (must match commentator).

The time bridge is the spine of time-honesty: race-relative seconds -> the
original 2024 wall-clock ns, used as the `through_time_ns` upper bound on every
BigQuery call. It MUST be identical to solution/commentator/config.py.
"""

RACE_ID = "berlin_2024_r10"

# Data range: this race + 10 seasons of career/results, bounded to the moment.
ALLOW_CAREER_HISTORY = True

# Green flag: 2024-05-12T13:04:05.726Z.
# TODO(student): set RACE_START_EPOCH_NS and implement race_time_to_wall_ns.
# RACE_START_EPOCH_NS = 1_715_519_045_726_000_000
#
# def race_time_to_wall_ns(race_time_s: int) -> int:
#     """Race-relative seconds → 2024 wall-clock ns. Use as through_time_ns (BQ)."""
#     ...
