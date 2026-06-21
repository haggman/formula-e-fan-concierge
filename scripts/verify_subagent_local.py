"""Local verification for the race-data subagent — no GCP, no LLM, no creds.

Exercises the DETERMINISTIC first-light path through the real FastAPI app with a
canned moment, proving the parts that don't need the cloud:

  - POST /ask_race_data answers a live-moment question (refused_future=false)
  - the computed race_wall_time_ns matches the clock bridge exactly
  - POST /ask_race_data refuses a "who wins?" future question (refused_future=true)
  - /healthz is up

What it does NOT cover (needs the deployed service — see
deploy/RUNBOOK_race_data_subagent.md): live Firestore "now", BigQuery via
fe-toolbox, the real LLM agent, and the CX wire/auth.

Run:  pip install fastapi pydantic httpx
      python scripts/verify_subagent_local.py
Exit code 0 = all checks passed.
"""
from __future__ import annotations

import os
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
PKG = REPO / "solution" / "race_data_subagent"

# DETERMINISTIC first-light, canned moment (no data plane).
os.environ["DETERMINISTIC"] = "1"
os.environ.setdefault("FE_STUB_RACE_TIME_S", "900")
os.environ.pop("TOOLBOX_URL", None)

# Make `shared` (repo root), `race_data_subagent` (under solution/), and `app`
# (the package dir) importable — mirrors the container's sys.path.
for p in (str(REPO), str(REPO / "solution"), str(PKG)):
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi.testclient import TestClient  # noqa: E402

import app as service  # solution/race_data_subagent/app.py  # noqa: E402
from race_data_subagent.config import (  # noqa: E402
    RACE_START_EPOCH_NS,
    race_time_to_wall_ns,
)

client = TestClient(service.app)
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        failures.append(name)


print("race-data subagent — local verification (DETERMINISTIC, canned moment)\n")

# Clock bridge sanity (the spine of time-honesty).
expected_wall = RACE_START_EPOCH_NS + 900 * 1_000_000_000
check("clock bridge constant", RACE_START_EPOCH_NS == 1_715_519_045_726_000_000,
      f"RACE_START_EPOCH_NS={RACE_START_EPOCH_NS}")
check("race_time_to_wall_ns(900)", race_time_to_wall_ns(900) == expected_wall,
      f"{race_time_to_wall_ns(900)}")

# Health.
r = client.get("/healthz")
check("/healthz 200", r.status_code == 200, str(r.json()))

# Live-moment question — must answer, not refuse, with the bridged wall time.
r = client.post("/ask_race_data", json={"question": "how is car 13 doing right now?"})
j = r.json()
check("live-moment 200", r.status_code == 200)
check("live-moment refused_future=false", j.get("refused_future") is False, str(j.get("answer"))[:80])
check("live-moment mode=deterministic", j.get("mode") == "deterministic")
check("live-moment race_wall_time_ns bridged", j.get("race_wall_time_ns") == expected_wall,
      f"{j.get('race_wall_time_ns')} == {expected_wall}")
check("live-moment now_source=canned", j.get("now_source") == "canned", str(j.get("now_source")))

# Future question — must refuse, no spoiler.
r = client.post("/ask_race_data", json={"question": "who wins the race?"})
j = r.json()
check("future 200", r.status_code == 200)
check("future refused_future=true", j.get("refused_future") is True, str(j.get("answer"))[:80])
check("future answer has no winner", "win" not in j.get("answer", "").lower()
      or "spoil" in j.get("answer", "").lower())

# A couple more future phrasings the keyword guard must catch.
for q in ("who is on the podium?", "what are the final results?", "predict the finish"):
    jj = client.post("/ask_race_data", json={"question": q}).json()
    check(f"future refused: {q!r}", jj.get("refused_future") is True)

print()
if failures:
    print(f"FAILED ({len(failures)}): {', '.join(failures)}")
    sys.exit(1)
print("ALL CHECKS PASSED")
