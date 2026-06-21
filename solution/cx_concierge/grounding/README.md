# CX grounding assets (rules pack + profiles)

Source documents for the CX concierge's RAG data store. **Authored / generated**, not
harvested — the staged FE dataset has no driver-bio/team-history corpus and no rules
document (PLAN.md §5). This folder is where the grounding content lives so it's
version-controlled; a Vertex AI Search data store is then pointed at it (next step).

## Contents

- **`rules/`** — the FE rules pack (DONE). Hand-authored from the data dictionary's
  authoritative "Resolved Findings" + Berlin-S10 metadata: Attack Mode, energy, race
  format, the Tempelhof circuit, the Gen3 car, tyres, race control/flags, glossary.
  Cross-checked against the FIA regulations (see `rules/README.md`).
- **`build_profiles.ipynb`** — Colab Enterprise notebook that **generates** the driver +
  team profiles. It reads the FE entry list + career stats from `gs://class-demo/...`
  **read-only**, uses Vertex AI Gemini to write several-paragraph profiles **grounded in
  the structured stats** (so car numbers, short codes, teams, and career figures match the
  dataset and nothing is invented), and writes **new** artifacts back to the shared
  `class-demo` bucket under a new `formula-e/grounding/` prefix — `driver_profiles.parquet`,
  `team_profiles.parquet`, and per-profile `.md` docs — so students receive ready-made
  profiles alongside the rest of the staged data. **Additive only:** the FE source files
  are never modified.
- **`profiles/`** — where the generated per-profile `.md` docs are committed (download the
  notebook's `gs://…/profiles/drivers|teams/*.md` output into here). RAG-ready.

## Pipeline

1. Rules store sources — stage both to `grounding/rules/`:
   - the **official FIA Season 10 regulation PDFs** (Sporting + Technical) from
     https://www.fia.com/regulation/category/109 (authoritative depth; Layout Parser); and
   - the concise authored pack as **`.txt`** (quick fan answers; Vertex AI Search ingests
     TXT/PDF/HTML, not `.md`):
     `for f in rules/*.md; do gcloud storage cp "$f" "gs://class-demo/formula-e/grounding/rules/$(basename "${f%.md}").txt"; done`
2. Run `build_profiles.ipynb` in Colab Enterprise → **comprehensive** parquet + `.txt`
   (ingestion) profiles for **all FE drivers + teams** + `profiles.jsonl`, written to
   `gs://class-demo/formula-e/grounding/profiles/`; commit the `.txt` into `profiles/` for
   version control. The notebook's final cell **updates the dataset catalog**
   (`reference/data_manifest.json` + `data_dictionary.md`) idempotently, backing both up to
   `reference/_backups/<ts>/` first.
3. **Index for CX (students, in the UI):** create **two** Vertex AI Search data stores —
   **FE Rules** (over `grounding/rules/`) and **Driver & Team Profiles** (over
   `grounding/profiles/`) — and attach both to the concierge as a **Data store tool**. Full
   walkthrough in `../DATASTORE_SETUP.md`. (Instructor stages the `.txt` corpus; students do
   the data stores + wiring as the grounding lesson — same pattern as the MLB build.)
4. The concierge combines the data store (bios/rules) + the race-data subagent (live/stats)
   + **Google Search** (long tail), grounded so it answers only from those sources.
