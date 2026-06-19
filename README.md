# Formula E — The Race-Day Companion (Challenge 1)

A second-screen fan companion over the Berlin 2024 (R10) replay. The front end is
**given** (interactive track map + car list + click-to-select + live stats panel).
Students build **three backend agents**:

1. **Commentator** (`*/commentator/`) — an **ADK** live broadcaster. Narrates the whole
   field in third person; when the fan selects a car, it narrows focus to that car. Spoken
   via TTS. Field-wide POV, boosted toward the selected car.
2. **CX Concierge** (`*/cx_concierge/`) — a **CX / Conversational Agents** orchestrator.
   Answers fan questions; grounds on RAG data stores (team/driver profiles, rules) + Google
   Search; delegates race/stats questions to the race-data subagent.
3. **Race-Data Subagent** (`*/race_data_subagent/`) — an **ADK** agent that owns **both**
   worlds: Firestore "now" + BigQuery "then" (10 seasons career/results + R10), **time-honest**.
   Runs on **Cloud Run** and serves its own `POST /ask_race_data` **OpenAPI** endpoint; CX calls it
   via an **OpenAPI tool** (Service Agent ID Token). Validated live — see `spec/cx_integration_spike.md`.

This repo is a **clean fork of the Challenge 2 chassis** (`../formula-e-race-engineer/`),
vendoring the pieces we keep and rebuilding the rest. See `spec/architecture.md` for the
locked target architecture and `spec/` for every conversion spec.

## Layout

```
simulator/        Race replayer (Cloud Run) → Pub/Sub.            [KEPT from Ch2]
state_writer/     Pub/Sub → Firestore "now".                      [CONVERT → Worker Pool, spec]
toolbox/          MCP Toolbox — 14 curated BigQuery tools.         [KEPT from Ch2]
shared/           Pydantic models, scorer, Firestore reader.       [KEPT; scorer RE-AIMED, spec]
setup/            Numbered setup scripts 1–6 + helpers.            [KEPT; step 5 rewritten, spec]
deploy/           Per-service deploy scripts.                      [KEPT; state_writer rewritten]
frontend/         GIVEN fan UI (map, car list, stats, CX widget).  [base from Ch2 — reworked]
scripts/          Local test / smoke / probe utilities.            [KEPT from Ch2]
docs/             architecture.svg.                                [REBUILD, plan in spec/]

starter/          What students build INTO (blanks + TODOs):
  commentator/         ADK broadcaster
  cx_concierge/        CX app config + grounding assets
  race_data_subagent/  ADK BQ+Firestore agent, MCP server

solution/         Reference build of all three packages.
spec/             Conversion + integration specs (the source of truth for the build).
```

## Three agents, three sub-teams

The package split is also the team split: one group owns the commentator, one owns the CX
concierge, one owns the race-data subagent. They share `shared/` (models, Firestore reader,
the scorer pattern) and the given data plane (simulator → Pub/Sub → state writer → Firestore).

## Quick start

```bash
source activate.sh          # exports PROJECT_ID/REGION/TOOLBOX_URL etc.
bash setup/all.sh           # runs steps 1–6 (data plane + toolbox + state writer + simulator)
```

> Reuse from Ch2 is a **feature**, not a shortcut — the graded new learning lives in the UI
> interactivity, the selection-aware commentary, the CX build + grounding, and the two-engine
> composition. See `STUDENT_GUIDE.md` (to be authored) and `spec/architecture.md`.
