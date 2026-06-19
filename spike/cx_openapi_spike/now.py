"""Firestore "now" read + the Ch2 clock bridge — self-contained for the spike.

The race-data subagent's window into the live replay. Mirrors
shared/state_client.py (reads race_states/{race_id}, field race_time_s) but
without importing shared.models, so the spike deploys as a standalone service.

If the live "now" doc isn't present (data plane not up yet), we fall back to a
canned race_time_s (FE_STUB_RACE_TIME_S) so the CX wire can still be proven end
to end before the simulator is running. The CX-facing contract is identical
either way; only `source` changes ("firestore" vs "canned").
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------
# Time bridge — MUST match solution/race_data_subagent/config.py and the
# commentator. Green flag: 2024-05-12T13:04:05.726Z.
# ----------------------------------------------------------------------------
RACE_START_EPOCH_NS = 1_715_519_045_726_000_000


def race_time_to_wall_ns(race_time_s: float) -> int:
    """Race-relative seconds -> 2024 wall-clock ns. Use as through_time_ns (BQ)."""
    return RACE_START_EPOCH_NS + int(race_time_s * 1_000_000_000)


def _project_id() -> str:
    # On the managed Agent Runtime, GOOGLE_CLOUD_PROJECT is the project NUMBER,
    # which makes Firestore 404. PROJECT_ID is always the ID — prefer it.
    pid = os.environ.get("PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not pid:
        raise RuntimeError("PROJECT_ID (or GOOGLE_CLOUD_PROJECT) env var required")
    if pid.isdigit():
        logger.warning(
            "project resolved to a numeric NUMBER (%s); Firestore will 404 — "
            "set PROJECT_ID to the project ID", pid,
        )
    return pid


def read_now() -> dict:
    """Return the replay's current moment.

    {race_time_s, race_wall_time_ns, source}. source is "firestore" when read
    from race_states/{race_id}, else "canned".
    """
    race_id = os.environ.get("RACE_ID", "berlin_2024_r10")

    # Try the live plane first.
    try:
        from google.cloud import firestore  # imported lazily so canned mode needs no creds

        db = firestore.Client(project=_project_id())
        doc = db.collection("race_states").document(race_id).get()
        if doc.exists:
            data = doc.to_dict() or {}
            rt = data.get("race_time_s")
            if rt is not None:
                return {
                    "race_time_s": float(rt),
                    "race_wall_time_ns": race_time_to_wall_ns(float(rt)),
                    "source": "firestore",
                }
            logger.warning("race_states/%s has no race_time_s field", race_id)
        else:
            logger.warning("race_states/%s does not exist yet — using canned moment", race_id)
    except Exception as e:  # noqa: BLE001 — spike: never let a missing data plane break the wire
        logger.warning("Firestore 'now' read failed (%s) — using canned moment", e)

    canned = float(os.environ.get("FE_STUB_RACE_TIME_S", "900"))  # 15:00 into the race
    return {
        "race_time_s": canned,
        "race_wall_time_ns": race_time_to_wall_ns(canned),
        "source": "canned",
    }


# Cheap heuristic for the time-honesty negative check. The real subagent enforces
# this mechanically (through_time_ns bound) + by prompt; the stub proves the wire
# refuses a "who wins?" style future question deterministically.
_FUTURE_MARKERS = (
    "who wins", "who win", "who won", "winner", "win the race", "going to win",
    "final result", "final results", "podium", "who finishes", "who will finish",
    "end of the race", "predict", "what happens next", "rest of the race",
)


def is_future_question(question: str) -> bool:
    q = (question or "").lower()
    return any(m in q for m in _FUTURE_MARKERS)
