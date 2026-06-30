"""SUPERSEDED — use scripts/local_commentator.py.

This was Ch2's race-engineer trigger harness. The Race-Day Companion's commentator
is a continuous play-by-play broadcaster; its harness is
`scripts/local_commentator.py` (mirrors `frontend/commentator_loop.py`).

Safe to delete (`git rm scripts/local_test.py`). Kept as a tombstone only because
this environment couldn't remove the file directly.
"""
import sys

print(__doc__)
print("Run instead:  python scripts/local_commentator.py --duration 180 "
      "[--select <car>]")
sys.exit(1)
