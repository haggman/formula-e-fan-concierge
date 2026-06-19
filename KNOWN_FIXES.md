# Known fixes / skeleton gaps

Issues found while standing up and validating the repo on a fresh Qwiklabs project (2026-06-19). These must land in whatever copy becomes the student repo.

## 1. Missing `notebooks/bq_setup.py` (blocks setup step 2) — FIXED

`setup/2_load_bigquery.sh` runs `python notebooks/bq_setup.py`, but the `notebooks/` directory was never vendored from the Challenge 2 chassis, so `setup/all.sh` aborted at step 2:

```
python: can't open file '.../formula-e-fan-concierge/notebooks/bq_setup.py': [Errno 2] No such file or directory
```

**Fix applied:** vendored `notebooks/bq_setup.py` from `../formula-e-race-engineer/notebooks/bq_setup.py`. It's the correct loader — builds `fe_race10` with the 11 tables + 3 views the banner and `setup/verify_checks.py` expect, including `career_driver`/`career_race` (the 10-season career data the Ch1 subagent ranges over) and the Hive-partitioned `telemetry` + materialized `top_speed_per_lap`. All other setup steps (3–6) reference files that already exist.

## 2. `setup/verify` has no such file — use `setup/verify.sh`

The verify script is `setup/verify.sh` (or just rerun `bash setup/all.sh`, which verifies at the end). `bash setup/verify` fails with "No such file or directory".

## 3. "Regional Access Boundary … Account not found" noise during verify — benign

`setup/verify.sh` prints scary-looking lines interleaved with its green checks:

```
Regional Access Boundary HTTP request failed after retries: response_data={'error': {'code': 404,
'message': 'Account not found for email: <hash>|student-03-...@qwiklabs.net', 'status': 'NOT_FOUND'}}
```

These are **not failures** — every check still passes (real row counts, fresh RaceState, indexes READY). Best read: the Google client/auth stack does a Regional Access Boundary resolution keyed to the caller identity; on Qwiklabs that identity is the **ephemeral student account**, which isn't resolvable in that backend → 404, retried, logged, then ignored because no access boundary is enforced. Environment-specific to Qwiklabs; unlikely to appear with a normal principal. Does not affect the data plane or the CX spike (Cloud Run + CX authenticate as *service* identities). Optional polish: add a logging filter in `verify_checks.py` to swallow that specific retry log so student output is clean.
