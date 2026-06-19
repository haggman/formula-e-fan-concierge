# CX grounding assets (profiles + rules pack)

Source documents for the CX concierge's RAG data store. **Authored**, not harvested — the
staged dataset has no driver-bio/team-history corpus and no rules document (confirmed in
PLAN.md §5). Authoring + indexing is the Knowledge-Base & RAG conversation's job; this
folder is where the source lands so it's version-controlled.

Planned contents (stubs to be filled):

- `rules/attack_mode.md`, `rules/energy.md`, `rules/race_format.md` — the FE rules pack,
  seeded from the data dictionary's "Resolved Findings" (AM = +50 kW, 2 activations, 240 s
  budget, scenarios, energy normalization, race format).
- `profiles/drivers/` — one short profile per entrant, synthesized from the structured entry
  list + career stats (+ public info).
- `profiles/teams/` — team/manufacturer history.

Indexing target: **Vertex AI Search** data store (decision #6 leans managed). The CX app
attaches it via a **Data store / File search tool**. Google Search grounding covers the long
tail so bio depth can stay light.
