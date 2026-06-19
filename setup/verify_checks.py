"""Green-light verification for the deployed data plane.

Run via setup/verify.sh, which discovers SIM_URL / TOOLBOX_URL from Cloud Run
and requires the activated venv. Five checks:

  1. Simulator      /status reachable, frames loaded, no publish errors
  2. Firestore      RaceState doc FRESH — this one check proves the whole
                    chain: simulator -> Pub/Sub -> State Writer -> Firestore
  3. Indexes        race_events composite indexes READY (admin API; waits
                    up to VERIFY_INDEX_WAIT_S=600 — setup submits builds
                    async, this is the one place that genuinely needs them)
  4. BigQuery       fe_race10 row sanity (laps, telemetry)
  5. MCP Toolbox    toolset 'race-engineer' loads all 14 tools

Exit code = number of failed checks (0 = green light).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import urllib.request

EXPECTED_TOOLS = 14
EXPECTED_INDEXES = 3
FRESH_S = 30
INDEX_WAIT_S = int(os.environ.get("VERIFY_INDEX_WAIT_S", "600"))

fails = 0


def ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def note(msg: str) -> None:
    print(f"  ○ {msg}")


def bad(msg: str) -> None:
    global fails
    fails += 1
    print(f"  ✗ {msg}")


def get_json(url: str, timeout: int = 10) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def main() -> int:
    global fails

    # ------------------------------------------------------------------
    print("== 1/5 Simulator ==")
    sim_url = os.environ.get("SIM_URL", "").rstrip("/")
    paused = False
    race_done = False
    if not sim_url:
        bad("SIM_URL not set — is fe-simulator deployed? (setup/6_deploy_simulator.sh)")
    else:
        try:
            st = get_json(f"{sim_url}/status")
            paused = bool(st.get("paused"))
            sr = st.get("seconds_remaining")
            race_done = sr is not None and float(sr) <= 1.0
            ok(f"sim reachable — t={st.get('race_time_s')}s, "
               f"frames_loaded={st.get('frames_loaded')}, paused={paused}, "
               f"publish_count={st.get('publish_count')}")
            if not st.get("frames_loaded"):
                bad("sim reports 0 frames loaded — check FRAMES_BUCKET/FRAMES_PATH and bucket access")
            if st.get("error_count"):
                bad(f"sim error_count={st['error_count']}: {str(st.get('last_error', ''))[:120]}")
        except Exception as e:
            bad(f"sim /status failed: {e}")

    # ------------------------------------------------------------------
    print("== 2/5 Firestore (proves the whole data plane end-to-end) ==")
    try:
        from google.cloud import firestore
        db = firestore.Client(project=os.environ["PROJECT_ID"])
        race_id = os.environ.get("RACE_ID", "berlin_2024_r10")
        # Bounded read: if setup hasn't run (no Firestore DB / API off) this
        # raises fast instead of retrying — verify reports the miss, no hang.
        doc = db.collection("race_states").document(race_id).get(timeout=15)
        if not doc.exists:
            bad(f"race_states/{race_id} missing — has the sim published since the "
                "State Writer deployed? RESTART the sim and re-verify.")
        else:
            age = int(time.time()) - int(doc.to_dict().get("updated_at_unix") or 0)
            if age <= FRESH_S:
                ok(f"RaceState fresh (updated {age}s ago) — "
                   "sim → Pub/Sub → State Writer → Firestore all working")
            elif paused:
                note(f"RaceState {age}s old, but the sim is PAUSED — "
                     "resume or RESTART it and re-verify if unsure")
            elif race_done:
                bad(f"RaceState stale ({age}s old) because the race FINISHED "
                    "(sim at the chequered flag, LOOP off) — staleness is "
                    "expected, but end-to-end is unproven: RESTART the sim "
                    "(SIM bar, or POST $SIM_URL/restart) and re-run verify. "
                    "Tip: LOOP on keeps a long-lived stack always verifiable.")
            else:
                bad(f"RaceState stale ({age}s old) with the sim mid-race — "
                    "check fe-state-writer logs and the Pub/Sub push subscription")
    except Exception as e:
        bad(f"Firestore check failed: {e}")

    # ------------------------------------------------------------------
    print("== 3/5 Firestore composite indexes (race_events) ==")
    # Structured admin API — no gcloud text-scraping. (The old setup-script
    # poll filtered on a key gcloud no longer exposes and spun blind for 15
    # minutes; this is its replacement, in the one place that needs it.)
    try:
        from google.cloud.firestore_admin_v1 import FirestoreAdminClient
        admin = FirestoreAdminClient()
        parent = (f"projects/{os.environ['PROJECT_ID']}/databases/(default)/"
                  "collectionGroups/race_events")

        def index_states():
            # Bounded so a not-yet-set-up project fails fast (no DB / API off).
            idx = list(admin.list_indexes(parent=parent, timeout=20))
            return ([i for i in idx if i.state.name == "READY"],
                    [i for i in idx if i.state.name == "CREATING"])

        ready, creating = index_states()
        waited = 0
        while len(ready) < EXPECTED_INDEXES and creating and waited < INDEX_WAIT_S:
            if waited == 0:
                note(f"{len(ready)}/{EXPECTED_INDEXES} READY, {len(creating)} still "
                     f"building — waiting (event queries need them; "
                     f"up to {INDEX_WAIT_S}s)...")
            time.sleep(15)
            waited += 15
            ready, creating = index_states()
            if waited % 60 == 0:
                note(f"  ...{len(ready)}/{EXPECTED_INDEXES} READY after {waited}s")
        if len(ready) >= EXPECTED_INDEXES:
            ok(f"race_events composite indexes: {len(ready)} READY"
               + (f" (waited {waited}s)" if waited else ""))
        elif creating:
            bad(f"indexes still building after {waited}s — no action needed, "
                "they will finish; re-run setup/verify.sh in a few minutes")
        else:
            bad(f"only {len(ready)}/{EXPECTED_INDEXES} READY and none building — "
                "rerun setup/4_setup_firestore.sh")
    except Exception as e:
        bad(f"index check failed: {e}")

    # ------------------------------------------------------------------
    print("== 4/5 BigQuery ==")
    try:
        from google.cloud import bigquery
        bq = bigquery.Client(project=os.environ["PROJECT_ID"],
                             location=os.environ["REGION"])
        # Bounded query + result waits: a missing dataset / disabled API raises
        # fast rather than hanging when setup hasn't run.
        laps = list(bq.query("SELECT COUNT(*) AS n FROM `fe_race10.laps`",
                             timeout=30).result(timeout=30))[0].n
        telem = list(bq.query("SELECT COUNT(*) AS n FROM `fe_race10.telemetry`",
                              timeout=30).result(timeout=30))[0].n
        if laps >= 800:
            ok(f"fe_race10.laps: {laps} rows")
        else:
            bad(f"fe_race10.laps: {laps} rows (expected ≥800) — rerun setup/2_load_bigquery.sh")
        if telem >= 1_000_000:
            ok(f"fe_race10.telemetry: {telem:,} rows")
        else:
            bad(f"fe_race10.telemetry: {telem:,} rows (expected ≥1M) — rerun setup/2_load_bigquery.sh")
    except Exception as e:
        bad(f"BigQuery check failed: {e}")

    # ------------------------------------------------------------------
    print("== 5/5 MCP Toolbox ==")
    toolbox_url = os.environ.get("TOOLBOX_URL", "").rstrip("/")
    if not toolbox_url:
        bad("TOOLBOX_URL not set — is fe-toolbox deployed? (setup/3_deploy_toolbox.sh)")
    else:
        async def _load():
            from toolbox_core import ToolboxClient
            async with ToolboxClient(toolbox_url) as client:
                return await client.load_toolset("race-engineer")
        try:
            tools = asyncio.run(_load())
            if len(tools) == EXPECTED_TOOLS:
                ok(f"toolset 'race-engineer' loads: {EXPECTED_TOOLS}/{EXPECTED_TOOLS} tools")
            else:
                bad(f"toolset loaded {len(tools)} tools, expected {EXPECTED_TOOLS} — "
                    "tools.yaml out of date in the staging bucket? rerun setup/3_deploy_toolbox.sh")
        except Exception as e:
            bad(f"Toolbox check failed: {e}")

    # ------------------------------------------------------------------
    print()
    if fails:
        print(f"✗ {fails} check(s) failed — fix before the event (each ✗ names its setup script)")
    else:
        print("✓ GREEN LIGHT — the data plane is fully up")
    return fails


if __name__ == "__main__":
    sys.exit(main())
