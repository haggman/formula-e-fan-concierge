"""SUPERSEDED — see frontend/commentator_loop.py.

This was Ch2's race-engineer trigger loop (a silence-gated event reactor). The
Race-Day Companion replaced it with `frontend/commentator_loop.py`
(`CommentatorLoop`) — a continuous play-by-play broadcaster that uses the scorer
as a director rather than a gate. Nothing imports this module any more.

Safe to delete (`git rm frontend/engineer_loop.py`). Kept as an empty tombstone
only because this environment couldn't remove the file directly.
"""
