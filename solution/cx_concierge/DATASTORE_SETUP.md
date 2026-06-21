# Grounding the CX concierge — data stores (student UI guide)

Give the concierge its **knowledge base**: two Vertex AI Search data stores over
the staged grounding corpus — **FE Rules** and **Driver & Team Profiles** — then
attach them to the CX concierge as a **Data store tool**. This is a **console /
UI** task (no code), and it follows the same pattern as the MLB "front-office"
build: separate stores for separate knowledge surfaces.

It pairs with `race_data_subagent/CX_SETUP.md` (the OpenAPI tool for live race +
stats) and Google Search (the long tail). Together: bios/rules from the data
stores, live/time-honest stats from the subagent, everything else from Search.

> Console naming: Vertex AI Search data stores live on the **AI Applications**
> page (part of the Gemini Enterprise platform); CX is **Conversational Agents /
> CX Agent Studio**. The flow is current as of 2026-06; menus may shift slightly.

## Prerequisites (instructor has staged these)

The grounding corpus is staged in GCS (Vertex AI Search ingests TXT/PDF/HTML/DOCX —
**not** `.md`), in two folders:

- `class-demo/formula-e/grounding/rules/` — the **official FIA Season 10 regulation
  PDFs** (Sporting + Technical) for authoritative depth, **plus** the concise authored
  rules pack (`*.txt`) for quick fan answers.
- `class-demo/formula-e/grounding/profiles/` — **comprehensive** driver + team profiles
  (`drivers/*.txt`, `teams/*.txt`) — every FE driver in the career table and every team in
  the 10-season results, not just the R10 field. (The `.parquet`/`.jsonl` siblings are
  ignored by document ingestion.)

APIs enabled: **Discovery Engine / AI Applications** and **Conversational Agents**.

## Why two data stores (not one)

Each data store is its own retrieval (RAG) index. Keeping **rules** separate from
**profiles** keeps each retrieval surface clean — a rules question retrieves from
the rules index, a "who is this driver" question from the profiles index — and
you can still query both together from one tool. Mixing them muddies relevance.
(Same reasoning as the MLB rulebook-vs-profiles split.)

## Part 1 — Create the two data stores

You can create them on the **AI Applications** page (**Data Stores → + Create
data store**) or inline from CX later (**+ Tool → Data store → create new**).
Either way the steps are the same; do it once per store.

**Store A — FE Rules**

1. Source: **Cloud Storage**.
2. Data type: **Unstructured Data Import (Document Search & RAG)** → **Documents**.
3. Synchronization frequency: **One time** (the rules pack is a versioned doc, not a live feed).
4. Select **Folder**, enter: `class-demo/formula-e/grounding/rules`
5. Name: `FE Rules`.
6. **Document processing / parser:** this folder holds the **FIA regulation PDFs**, so set the
   **Layout Parser** (same choice as the MLB rulebook) — it preserves the section/clause
   hierarchy that makes retrieval relevant on a structured regs document. The concise `.txt`
   pack in the same folder parses fine under it too. Leave **chunking** on for RAG.
   (Layout parsing adds a Document AI charge at ingestion only.)
7. **Create.** Ingestion runs in the background.

**Store B — Driver & Team Profiles**

8. **+ New data store** again → **Cloud Storage** → **Unstructured / Documents** → **One time**.
9. Folder: `class-demo/formula-e/grounding/profiles` (recurses into `drivers/` + `teams/`).
10. Name: `Driver and Team Profiles`. These are plain `.txt`, so the **default digital parser**
    is right here (no Layout Parser needed). Chunking on. **Create.** (This is the larger
    ingest — every FE driver + team — so it takes a bit longer.)

> Note: importing from GCS does **not** carry Cloud Storage IAM — anyone with
> data-store access can read the indexed content. Fine here (public 2024 race
> bios/rules), but worth knowing.

## Part 2 — Attach to the CX concierge

1. Open **Conversational Agents / CX Agent Studio** (`ces.cloud.google.com`), select
   your project and the concierge agent.
2. **Tools → + Create.** Type: **Data store**. Name it `fe_knowledge`.
3. Add **both** data stores to the tool (`FE Rules` and `Driver and Team Profiles`).
   (One tool can query multiple stores; or make two tools if you want explicit
   routing.)
4. **Grounding settings:** set the **minimum grounding confidence** (VERY_LOW →
   VERY_HIGH) — start at **LOW/MEDIUM**, raise it if answers look weak; responses
   below the threshold are withheld. Keep the **grounding heuristics** filter on.
5. Save.

## Part 3 — Tell the agent when to use it

In the agent's instructions/playbook:

> For questions about a driver's or team's background, history, or who they are,
> and for Formula E rules (Attack Mode, energy, race format, the circuit, the car,
> tyres, flags), answer **only** from the `fe_knowledge` data store. For anything
> about the live race or in-race statistics ("how's car 13 now?", standings, lap
> times, career numbers during the race), use the `ask_race_data` tool. Never
> state race facts from your own knowledge, and never reveal anything the race
> tool declines to answer.

This keeps the grounded sources separated: data store for static bio/rules
knowledge, the race-data subagent for live + time-honest stats.

## Part 4 — Test in the Simulator

- "**Who is António Félix da Costa?**" / "**Tell me about the Porsche team**" →
  grounded bio; the citation should point at a `profiles/...txt` doc.
- "**What is Attack Mode?**" / "**How does energy work?**" → grounded from `rules/...txt`.
- "**Who is da Costa's teammate?**" → from the profile's teammate line.
- Confirm the **citations** reference your data-store documents — that's proof the
  answer is grounded, not invented.

## Troubleshooting

- **0 documents imported** → the folder had no supported types. Confirm `.txt`
  files exist (Vertex AI Search does not ingest `.md`).
- **Answers look invented** → tighten the instruction ("answer only from the data
  store") and/or raise the grounding confidence level.
- **Citations missing / wrong store** → confirm both stores finished importing and
  the tool references them.

## Sources

- [Create a search data store (Cloud Storage)](https://docs.cloud.google.com/generative-ai-app-builder/docs/create-data-store-es)
- [Prepare data for ingesting (supported formats)](https://docs.cloud.google.com/generative-ai-app-builder/docs/prepare-data)
- [Data store tools — CX Agent Studio](https://docs.cloud.google.com/customer-engagement-ai/conversational-agents/ps/tool/data-store)
- [Data store tool settings (grounding confidence)](https://cloud.google.com/dialogflow/cx/docs/concept/data-store/settings)
