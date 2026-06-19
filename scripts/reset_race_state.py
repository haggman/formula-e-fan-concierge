"""Reset Firestore race state — wipe RaceState + all events for a race.

Use between replay sessions to start from a clean slate, or after schema
changes to the event stream (e.g. the frames_v1 → frames_v2 migration).

Deletes:
  - race_states/{race_id}            (the current-frame doc)
  - race_events/* where race_id matches (in batches of 500)

Usage:
    python scripts/reset_race_state.py            # prompts for confirmation
    python scripts/reset_race_state.py --yes      # no prompt (for scripts)
    python scripts/reset_race_state.py --race-id berlin_2024_r10

Note: if the simulator is publishing while this runs, new frames repopulate
Firestore immediately — that's fine and usually what you want (clean replay).
For a truly empty store, pause the simulator first: POST $SIM_URL/pause
"""
from __future__ import annotations

from shared.script_env import require_venv
require_venv()

import argparse
import os
import sys

from google.cloud import firestore

BATCH_SIZE = 500  # Firestore batch write limit


def delete_events(db: firestore.Client, race_id: str) -> int:
    """Delete all race_events docs for race_id. Returns count deleted."""
    deleted = 0
    while True:
        docs = list(
            db.collection("race_events")
            .where(filter=firestore.FieldFilter("race_id", "==", race_id))
            .limit(BATCH_SIZE)
            .stream()
        )
        if not docs:
            break
        batch = db.batch()
        for doc in docs:
            batch.delete(doc.reference)
        batch.commit()
        deleted += len(docs)
        print(f"  ... deleted {deleted} event docs", flush=True)
    return deleted


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--race-id", default=os.environ.get("RACE_ID", "berlin_2024_r10"))
    parser.add_argument("--yes", action="store_true", help="skip confirmation prompt")
    args = parser.parse_args()

    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("PROJECT_ID")
    if not project_id:
        print("ERROR: PROJECT_ID env var required. Run: source ./activate",
              file=sys.stderr)
        sys.exit(1)

    print(f"Project: {project_id}")
    print(f"Race:    {args.race_id}")
    print(f"Will delete race_states/{args.race_id} and ALL matching race_events docs.")

    if not args.yes:
        answer = input("Proceed? [y/N] ").strip().lower()
        if answer != "y":
            print("Aborted.")
            sys.exit(0)

    db = firestore.Client(project=project_id)

    # 1) RaceState doc
    state_ref = db.collection("race_states").document(args.race_id)
    if state_ref.get().exists:
        state_ref.delete()
        print(f"  ✓ deleted race_states/{args.race_id}")
    else:
        print(f"  ○ race_states/{args.race_id} did not exist")

    # 2) Event docs
    print("Deleting race_events docs...")
    count = delete_events(db, args.race_id)
    print(f"  ✓ deleted {count} event docs total")

    print("\nDone. Firestore is clean for this race.")
    print("If the simulator is running, new frames will repopulate within seconds.")


if __name__ == "__main__":
    main()