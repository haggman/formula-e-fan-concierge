# Grounding the CX concierge — Vertex AI Search data store (student UI guide)

How to give the concierge its **knowledge base**: create a Vertex AI Search data
store over the staged grounding corpus (FE rules + driver/team profiles), then
attach it to the CX agent as a **Data store tool**. This is a **console / UI**
task — no code. It pairs with `race_data_subagent/CX_SETUP.md` (the OpenAPI tool
for live + stats) and Google Search (the long tail).

> Console naming note: Vertex AI Search now lives under **AI Applications** (and
> is being rebranded "Agent Search"); CX is **Conversational Agents / CX Agent
> Studio**. Menus may shift slightly — the flow below is current as of 2026-06.

## Prerequisites (instructor has already done these)

- The grounding corpus is staged in GCS as **plain text** (Vertex AI Search
  ingests TXT/PDF/HTML/DOCX — **not** `.md`):
  - `gs://class-demo/formula-e/grounding/profiles/drivers/*.txt`
  - `gs://class-demo/formula-e/grounding/profiles/teams/*.txt`
  - `gs://class-demo/formula-e/grounding/rules/*.txt`
- APIs enabled: **AI Applications / Discovery Engine** (`discoveryengine.googleapis.com`)
  and **Dialogflow / Conversational Agents**.

## Part 1 — Create the data store (AI Applications console)

1. In the Cloud console go to **AI Applications** → **Data Stores** → **Create data store**.
2. **Source:** choose **Cloud Storage**.
3. **What to import:** select **Folder**, and enter
   `gs://class-demo/formula-e/grounding/` (it recurses into `rules/` and
   `profiles/`; non-text files like the `.parquet`/`.jsonl`/`.md` are skipped).
4. **Type of data:** **Unstructured documents**. (Optional but recommended for
   RAG: enable **document chunking** in the parsing/processing options.)
5. **Location:** `global` (matches the rest of the lab).
6. Give the data store a name, e.g. `fe-knowledge`, and **Create**. Ingestion runs
   in the background — wait until the documents show as imported (a few minutes).

> Heads-up: importing from GCS does **not** carry over Cloud Storage IAM — anyone
> with data-store access can read the indexed content. Fine here (public 2024 race
> bios/rules), but worth knowing.

## Part 2 — Add the Data store tool in CX

1. Open **Conversational Agents / CX Agent Studio** (`ces.cloud.google.com`),
   select your project and the concierge agent.
2. **Tools** → **+ Create**. **Type:** **Data store**. Name it `fe_knowledge`.
3. **Select the data store** you created (`fe-knowledge`). (CX can also create a
   Cloud Storage data store inline here, but you've already made one.)
4. **Grounding settings:** set the **minimum grounding confidence** (VERY_LOW →
   VERY_HIGH) — start at **LOW/MEDIUM** and raise it if you see weak answers; the
   agent withholds responses below the threshold. Leave the **grounding
   heuristics** filter on to suppress likely-hallucinated answers.
5. Save.

## Part 3 — Tell the agent when to use it (grounding instruction)

On the agent's instructions/playbook, route knowledge questions to the data store
and keep answers grounded:

> For questions about a driver's or team's background, history, or who they are,
> and for Formula E rules (Attack Mode, energy, race format, the circuit, the car,
> tyres, flags), answer **only** from the `fe_knowledge` data store. For anything
> about the live race or statistics ("how's car 13 now?", standings, lap times,
> career numbers during the race), use the `ask_race_data` tool. Never state facts
> from your own knowledge, and never reveal anything the race tool declines to
> answer.

This keeps the **two grounded sources** separated: the data store for static
bio/rules knowledge, the race-data subagent for live + time-honest stats.

## Part 4 — Test in the Simulator

- "**Who is António Félix da Costa?**" / "**Tell me about the Porsche team**" →
  grounded bio from the data store (cite shows a `profiles/...txt` doc).
- "**What is Attack Mode?**" / "**How does energy work in Formula E?**" → grounded
  from `rules/...txt`.
- "**Who's da Costa's teammate?**" → answered from the profile (teammate field).
- Confirm the **citations** point at your data-store documents — that's proof the
  answer is grounded, not invented.

## Troubleshooting

- **Data store imported 0 documents** → the source had no supported file types.
  Confirm `.txt` files exist under the folder (Vertex AI Search does not ingest
  `.md`). Re-run the instructor staging step.
- **Answers seem ungrounded / invented** → tighten the agent instruction
  ("answer only from the data store") and/or raise the grounding confidence level.
- **Tool returns nothing** → check the data store finished importing and the tool
  points at the right data store; check the agent has permission to the data store.

## Sources

- [Create a search data store (Cloud Storage)](https://docs.cloud.google.com/generative-ai-app-builder/docs/create-data-store-es)
- [Prepare data for ingesting (supported formats)](https://docs.cloud.google.com/generative-ai-app-builder/docs/prepare-data)
- [Data store tools — CX Agent Studio](https://docs.cloud.google.com/customer-engagement-ai/conversational-agents/ps/tool/data-store)
- [Data store tool settings (grounding confidence)](https://cloud.google.com/dialogflow/cx/docs/concept/data-store/settings)
