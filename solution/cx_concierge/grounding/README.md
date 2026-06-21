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
  dataset and nothing is invented), and writes **new** artifacts to a bucket we own:
  `driver_profiles.parquet`, `team_profiles.parquet`, and per-profile `.md` docs. The FE
  source data is never modified.
- **`profiles/`** — where the generated per-profile `.md` docs are committed (download the
  notebook's `gs://…/profiles/drivers|teams/*.md` output into here). RAG-ready.

## Pipeline

1. Author rules (`rules/`) — done.
2. Run `build_profiles.ipynb` in Colab Enterprise → new parquet + `.md` profiles in our
   bucket; commit the `.md` into `profiles/`.
3. **Index for CX:** point a **Vertex AI Search** data store at the `rules/` + `profiles/`
   docs (unstructured); optionally load the parquet into BigQuery for structured use.
4. The CX concierge attaches the data store via a **Data store / File search tool**, with
   **Google Search** grounding for the long tail.
