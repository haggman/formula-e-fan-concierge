"""Firestore reader for the race engineer agent's frame tools.

Reads RaceState from race_states/{race_id} and Events from race_events/{auto-id}.
A 1-second TTL cache on RaceState gives intra-turn consistency (multiple tool
calls within one agent reasoning turn see the same world) without hammering
Firestore.

Module-level singleton — instantiated once per agent process, persists cache
across tool calls.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

from google.cloud import firestore

from shared.models import Event, EventType, RaceState

logger = logging.getLogger(__name__)


class StateClient:
    """Thin Firestore wrapper for the frame tools.

    Caches the current RaceState for `cache_ttl_s` seconds. Events are not
    cached — they're queried with parameters that vary per call.
    """

    def __init__(
        self,
        project_id: str,
        race_id: str = "berlin_2024_r10",
        cache_ttl_s: float = 1.0,
    ):
        self.race_id = race_id
        self.cache_ttl_s = cache_ttl_s
        self._db = firestore.Client(project=project_id)
        self._cached_state: Optional[RaceState] = None
        self._cached_at: float = 0.0

    # ------------------------------------------------------------------
    # RaceState — cached read
    # ------------------------------------------------------------------

    def get_race_state(self, *, fresh: bool = False) -> Optional[RaceState]:
        """Return the current RaceState. None if Firestore doc doesn't exist.

        Cached for `cache_ttl_s` seconds. Pass fresh=True to bypass cache.
        """
        now = time.monotonic()
        if (
            not fresh
            and self._cached_state is not None
            and (now - self._cached_at) < self.cache_ttl_s
        ):
            return self._cached_state

        doc = self._db.collection("race_states").document(self.race_id).get()
        if not doc.exists:
            logger.warning("race_states/%s does not exist yet", self.race_id)
            self._cached_state = None
            self._cached_at = now
            return None

        try:
            state = RaceState.model_validate(doc.to_dict())
        except Exception as e:
            logger.exception("failed to parse RaceState doc: %s", e)
            return None

        self._cached_state = state
        self._cached_at = now
        return state

    def invalidate_cache(self) -> None:
        """Force the next get_race_state() to re-read from Firestore."""
        self._cached_state = None
        self._cached_at = 0.0

    # ------------------------------------------------------------------
    # Events — uncached queries
    # ------------------------------------------------------------------

    def query_events(
        self,
        *,
        from_race_time_s: Optional[int] = None,
        to_race_time_s: Optional[int] = None,
        event_types: Optional[list[EventType]] = None,
        car_involved: Optional[int] = None,
        limit: int = 50,
    ) -> list[Event]:
        """Query events with optional filters.

        Filters compose with AND. Results ordered newest-first.

        event_types is normalized defensively: EventType members or plain
        strings both work (Gemini-originated calls arrive as strings).
        """
        q = self._db.collection("race_events").where(
            filter=firestore.FieldFilter("race_id", "==", self.race_id)
        )

        if from_race_time_s is not None:
            q = q.where(
                filter=firestore.FieldFilter("race_time_s", ">=", from_race_time_s)
            )
        if to_race_time_s is not None:
            q = q.where(
                filter=firestore.FieldFilter("race_time_s", "<=", to_race_time_s)
            )
        if event_types:
            type_values = [
                t.value if isinstance(t, EventType) else str(t)
                for t in event_types
            ]
            q = q.where(
                filter=firestore.FieldFilter("event_type", "in", type_values)
            )
        if car_involved is not None:
            q = q.where(
                filter=firestore.FieldFilter("car_number", "==", car_involved)
            )

        q = q.order_by("race_time_s", direction=firestore.Query.DESCENDING).limit(limit)

        events: list[Event] = []
        for doc in q.stream():
            try:
                events.append(Event.model_validate(doc.to_dict()))
            except Exception as e:
                logger.warning("skipping malformed event doc %s: %s", doc.id, e)
        return events


# ----------------------------------------------------------------------------
# Module-level singleton
# ----------------------------------------------------------------------------

_singleton: Optional[StateClient] = None


def get_state_client() -> StateClient:
    """Get or initialize the process-wide StateClient singleton.

    Reads PROJECT_ID and RACE_ID from env. Called by the frame tools.
    """
    global _singleton
    if _singleton is None:
        # NEW
        # On Vertex AI Agent Engine, GOOGLE_CLOUD_PROJECT arrives as the
        # project NUMBER (e.g. 83898679865). Firestore rejects number-
        # addressed database paths with a misleading 404 "database (default)
        # does not exist". PROJECT_ID is always the ID — baked into the
        # engine .env by build_engine_app.py, set locally by activate.sh —
        # so prefer it.
        project_id = os.environ.get("PROJECT_ID") or os.environ.get(
            "GOOGLE_CLOUD_PROJECT"
        )
        if not project_id:
            raise RuntimeError(
                "PROJECT_ID (or GOOGLE_CLOUD_PROJECT) env var required"
            )
        if project_id.isdigit():
            logger.warning(
                "project resolved to a numeric project NUMBER (%s); Firestore "
                "will 404 — set PROJECT_ID to the project ID", project_id
            )
        race_id = os.environ.get("RACE_ID", "berlin_2024_r10")
        _singleton = StateClient(project_id=project_id, race_id=race_id)
    return _singleton