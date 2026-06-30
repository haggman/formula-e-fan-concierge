# Daily startup — Race-Day Companion

Coming back to a project that's **already built** (Cloud Shell, the GCP project from
before). This is the short "get it running again" path. Full details — offline
checks, live E2E, tuning — live in `deploy/RUNBOOK_commentator.md`.

## 1. Activate and launch the UI

```bash
cd ~/formula-e-fan-concierge                 # your clone
git pull                                     # pick up any pushed changes
export AGENT_PACKAGE=solution.commentator    # the reference commentator
source activate.sh                           # venv + project + Vertex env
export SIM_URL="$(gcloud run services describe fe-simulator --region "$REGION" --format='value(status.url)')"
uvicorn frontend.main:app --host 0.0.0.0 --port 8080
```

Then open **Cloud Shell → Web Preview → port 8080**.

> If `source activate.sh` errors with "no project set", run
> `gcloud config set project YOUR_PROJECT_ID` first (Qwiklabs usually remembers it).

## 2. Start the race from the page — no curl needed

In the **SIM** bar along the bottom of the page:

1. Click **RESTART** — rewinds to the green flag *and* starts it playing (restart
   also clears any pause from yesterday).
2. Set **2×** in the speed dropdown (good pace for commentary).
3. Optional: tick **LOOP** so it auto-restarts at the chequered flag.

Click **🔊 LIVE AUDIO** (top right) to hear the commentary spoken. The feed should
start within a few seconds. Click any car to **follow** it; **× field-wide** (or
just reload the page) goes back to the whole field.

That's the whole daily loop: activate → uvicorn → RESTART in the UI.

## If something's off

- **"SIM_URL is not set"** at launch → you skipped the `SIM_URL` export in step 1.
- **Feed silent / panel blank** → the sim is idle or paused; click **RESTART** in the
  SIM bar. If still nothing, the data plane is down — rebuild it: `bash setup/all.sh`.
- **Commentary stuck on one car** in field-wide → reload the page (that clears the
  server-side selection).
- **Quota 429s** → `export FE_MODEL=gemini-2.5-flash GOOGLE_CLOUD_LOCATION=us-central1`,
  re-source `activate.sh`, relaunch.

## Test without a browser

```bash
python scripts/local_commentator.py --duration 180 --verbose     # whole field
python scripts/local_commentator.py --select 13 --verbose        # follow car 13
```

(Or `python scripts/verify_commentator_offline.py` for the no-GCP logic check.)
