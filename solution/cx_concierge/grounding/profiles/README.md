# Profiles — generated grounding docs

This folder holds the **generated** driver and team profiles for the CX concierge's
RAG data store. They are produced by `../build_profiles.ipynb` (Colab Enterprise),
which reads the FE entry list + career stats **read-only** and uses Vertex AI Gemini
to write several-paragraph profiles **grounded in the structured stats**.

Expected layout once the notebook has run and you've committed its output:

```
profiles/
  drivers/<short_code>.md     e.g. dac.md, cas.md, eva.md   (one per R10 entrant)
  teams/<team-slug>.md        one per team
```

To populate: run `build_profiles.ipynb`, then download its
`gs://<PROJECT>-fe-grounding/profiles/drivers|teams/*.md` output into here so the docs
are version-controlled alongside the rules pack. The canonical `driver_profiles.parquet`
/ `team_profiles.parquet` stay in the bucket (and/or BigQuery) as the data artifacts.

Source data is never modified — these are new artifacts.
