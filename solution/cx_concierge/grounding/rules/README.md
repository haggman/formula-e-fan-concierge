# Rules pack — CX concierge grounding

Authored FE rules/knowledge docs for the concierge's RAG data store. The dataset
has **no** rules/regulations corpus (PLAN.md §5), so these are written from the
authoritative **"Resolved Findings"** + circuit/race metadata in
`formula-e_reference_data_dictionary.md`, scoped to **Berlin 2024 (Season 10),
Gen3**. Each doc is a self-contained, retrieval-friendly chunk with a topic
header and a "Quick facts" line.

| File | Covers |
|---|---|
| `attack_mode.md` | Attack Mode: +50 kW boost, Turn 2 zone, R09/R10 budgets, scenarios 1/2/3 |
| `energy.md` | Energy management, `percent_consumed` normalization, regen under SC |
| `race_format.md` | Lap-limited + 75-min cap, lap-extension formula, R09/R10 results |
| `circuit_berlin_tempelhof.md` | Tempelhof layout: 2,345 m / 15 turns, sectors, pit, AM zone |
| `car_gen3.md` | Gen3 car: 350 kW, 600 kW regen, 856 kg, vs Gen3 Evo |
| `tires.md` | Single Hankook all-weather tyre, no compound strategy |
| `race_control_and_flags.md` | SC / FCY / flags / penalties and their strategic effect |
| `glossary.md` | Quick definitions of the terms a fan will ask about |

**Provenance:** facts trace to the data dictionary's Resolved Findings and race
metadata, supplemented with well-established Gen3-era Formula E knowledge. Berlin
specifics (4-min R10 Attack Mode, Turn 2 zone, 2,345 m/15 turns, both rounds won
by #13) are dataset-confirmed. Google Search grounding in CX covers the long tail.

**Authoritative regulations:** the official FIA Formula E regulations (Sporting,
Technical, Operational) are the source of record and can be used to verify/extend
this pack: https://www.fia.com/regulation/category/109 — note season-to-season
changes; this pack is scoped to the 2024 Season 10 Berlin rounds.
