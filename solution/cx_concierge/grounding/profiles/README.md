# Profiles — generated, and they live in the bucket (not the repo)

The driver and team profiles are **generated build artifacts**, so they are **not
committed here**. The source of truth is the GCS bucket; this repo keeps the *recipe*
(the `../build_profiles.ipynb` notebook) and the authored `../rules/` source, not the
generated output.

**Where the profiles live (canonical):**

```
gs://class-demo/formula-e/grounding/profiles/
  drivers/<short_code>.txt        one per FE driver (comprehensive: all of the career table)
  teams/<team-slug>.txt           one per FE team (all teams in the 10-season results)
  driver_profiles.parquet         the structured table
  team_profiles.parquet
  profiles.jsonl                  records (id, metadata, content) for structured import
```

**To (re)generate:** run `../build_profiles.ipynb` in Colab Enterprise. It reads the FE
career/results tables **read-only**, writes the profiles to the bucket above (`.txt` is the
Vertex AI Search ingestion form), and updates the dataset catalog. It's verified five ways
(structural, identifier, coverage, spoiler-free, and an LLM fact-check judge).

**To use them:** the Vertex AI Search data store ingests from the bucket path above — see
`../../BUILD_CONCIERGE.md` (Step 1). The repo never needs a copy.
