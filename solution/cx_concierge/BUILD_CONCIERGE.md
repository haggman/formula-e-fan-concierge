# Build the CX Concierge — end-to-end

One guide, in order, to build the Race-Day Companion: a CX (Conversational Agents /
CX Agent Studio) **orchestrator** that answers any fan question by routing it to a
grounded tool — never from its own memory, and never spoiling the replay.

**We build it incrementally — add one tool, test it, watch how the agent behaves,
then grow the instructions to match.** That's the whole teaching arc: you *see* the
orchestrator gain each capability.

The three grounded sources we'll wire in:

| Tool | Type | For |
|---|---|---|
| `google_search` | Google Search (grounding) | current / real-world / off-dataset |
| `ask_race_data` | OpenAPI → the race-data subagent | live race + in-race stats, time-honest |
| `fe_knowledge` | Data store (both stores) | driver/team bios + FE rules |

> **Why this order:** data stores take ~10–15 min to index, so we **create them first
> (Step 1)** and let them index while we build and test the other two tools, then
> **attach them last (Step 7)** when they're ready. No dead time.

---

## Prerequisites

- The **race-data subagent is deployed** and answering (`setup/7_deploy_subagent.sh`;
  verify with `deploy/RUNBOOK_race_data_subagent.md`). Have its URL: `echo "$SUBAGENT_URL"`.
- The **grounding corpus is staged** in `gs://class-demo/formula-e/grounding/` (`rules/`
  = FIA PDFs + rules pack; `profiles/` = driver/team `.txt`).
- **APIs on:** `discoveryengine` + `dialogflow` (in `deploy/enable_apis.sh` / `setup/all.sh`).
- The deploy already granted `run.invoker` to the CES service agent (`gcp-sa-ces`), so the
  OpenAPI tool's auth will work; if it 401/403s later, open CX once and re-run the deploy.

---

## Step 1 — Create the two data stores (do this FIRST; don't attach yet)

On the **AI Applications** page → **Data Stores → + Create data store** (or later, inline
from CX **+ Tool → Data store → create new**). Make **two** stores — separate indexes keep
retrieval precise (bios vs rules).

**Store A — FE Rules**
1. Source **Cloud Storage** → data type **Unstructured Data Import (Document Search & RAG) → Documents** → sync **One time**.
2. **Folder:** `class-demo/formula-e/grounding/rules` · **Name:** `FE Rules`.
3. **Document processing options:** parser = **Layout Parser** (the folder holds the FIA
   regulation PDFs; layout parsing preserves the section/clause hierarchy that makes
   retrieval relevant). Turn on its advanced settings — **table annotations**, **image
   annotations**, **Gemini enhancement** — and **"Include ancestor headings in chunks."**
   If asked about a pricing model, keep the default (**general pricing**). **Create.**

**Store B — Driver & Team Profiles**
4. **+ New data store** → **Cloud Storage / Unstructured / Documents / One time**.
5. **Folder:** `class-demo/formula-e/grounding/profiles` (recurses into `drivers/` + `teams/`) · **Name:** `Driver and Team Profiles`.
6. These are plain `.txt`, so the **default digital parser** is right (no Layout Parser). General pricing. **Create.**

> Both now index in the background (~10–15 min). **Leave them — move straight to Step 2.**

---

## Step 2 — Create the agent + set its Goal

In **CX Agent Studio** (`ces.cloud.google.com`) → select the project → create an agent
(the **Root agent**). Paste this into its **Goal**:

```text
You are the Race-Day Companion, a friendly Formula E concierge for fans watching a live replay of the 2024 Berlin E-Prix (Round 10). Help fans follow the race as it happens and understand the drivers, teams, and rules. Always answer from your tools, never from your own memory, and never spoil what hasn't happened yet in the replay.
```

(The built-in `end_session` tool is added automatically — leave it; you don't reference it.)

---

## Step 3 — Add the `google_search` tool

**+ Tool → Google Search.**
- **Name:** `google_search`
- **Description:**
  ```text
  Grounded Google web search for current, real-world, or off-dataset questions that the other tools cannot answer — for example present-day Formula E news, the current-season championship standings, or general background not contained in this replay's data.
  ```
- **Excluded / Included domains:** leave blank. **Specific URLs:** leave blank. **Text Prompt:** keep the default.

## Step 4 — Instructions v1 (search only), then test

Paste this into **Instructions**:

```text
Route each fan question to a tool and answer only from what the tool returns.

- Current, real-world, or general-background questions (news, the present-day championship, anything not specific to this replay): use {@TOOL: google_search}.

Grounding (non-negotiable):
- Answer only from tool results. Never state facts from your own knowledge.
- If no tool can answer, say you don't have that information. Do not guess.

Voice:
- Be an enthusiastic, concise second-screen Formula E companion. Lead with the answer in 1-3 sentences, friendly, not formal.

Scope:
- Stay on Formula E and this race. Politely redirect unrelated requests back to the race.
```

**Test (Simulator):** "Who's leading the championship this season?" → calls `google_search`.
Try "How's car 13 right now?" too — it should say it doesn't have that yet (no race tool).
**Watch:** confirm it only answers from the tool and declines what it can't reach.

---

## Step 5 — Add the `ask_race_data` OpenAPI tool

This is the wire to your deployed subagent.
1. **+ Tool → OpenAPI.** **Name:** `ask_race_data`.
2. **Description:**
   ```text
   Authoritative, time-honest source for Berlin 2024 Round 10 race facts: live race state (positions, a car's speed/energy/Attack Mode, gaps, recent overtakes, lap times) and in-race statistics. Refuses anything in the replay's future.
   ```
3. **Schema:** paste `solution/race_data_subagent/openapi_ask_race_data.yaml`, with the
   schema's `SERVICE_URL` replaced by your **`$SUBAGENT_URL`** (`echo "$SUBAGENT_URL"`).
4. **Auth:** **Service agent ID token**. **Save.**

(Deeper reference / troubleshooting for this tool: `../race_data_subagent/CX_SETUP.md`.)

## Step 6 — Instructions v2 (+ live race + time-honesty), then test

Replace the Instructions with:

```text
Route each fan question to a tool and answer only from what the tool returns.

- Live race or in-race stats (current positions/standings, a car's speed, energy, or Attack Mode, gaps, what's happening now, recent overtakes or incidents, lap times, a driver's stats during this race): call {@TOOL: ask_race_data_ask_race_data} with the fan's question and answer from its answer field.
- Current, real-world, or off-dataset questions (news, the present-day championship, anything not specific to this replay): use {@TOOL: google_search}.

Grounding (non-negotiable):
- Answer only from tool results. Never state race facts, results, or statistics from your own knowledge.
- If no tool can answer, say you don't have that information. Do not guess.

Time-honesty (non-negotiable):
- The race is a live replay. {@TOOL: ask_race_data_ask_race_data} is time-honest and refuses questions about the future ("who wins?", "who's on the podium?", "how does it end?"). When it refuses, relay that refusal warmly and never reveal the result, the podium, or anything that hasn't happened yet — even if you think you know it, and even from Google Search.
- Questions about the OUTCOME of this event (the Berlin 2024 R9/R10 result, winner, podium, or finishing order) are always off-limits: treat them as spoilers and never answer them from any tool or from memory.

Voice:
- Be an enthusiastic, concise second-screen Formula E companion. Lead with the answer in 1-3 sentences, use driver short names and car numbers, friendly, not formal.

Scope:
- Stay on Formula E and this race. Politely redirect unrelated requests back to the race.
```

**Test:** "How's car 13 right now?" → answers from the live race · "Who wins the race?" →
**refuses** · "Who won the Berlin 2024 E-Prix?" → **refuses** (the Google Search spoiler
back-door is closed by the time-honesty lines). **Watch:** which tool each call uses, and
that no path leaks the result.

---

## Step 7 — Add the data store tool, `fe_knowledge`

(By now the Step-1 stores have finished indexing.) **+ Tool → Data store.**
- **Name:** `fe_knowledge`
- **Description:**
  ```text
  Formula E knowledge base. Driver and team profiles (who they are, careers, nationality, teams, team-mates) plus the sport's rules and how it works (Attack Mode, energy management, race format, the Tempelhof circuit, the Gen3 car, tyres, flags and safety cars). Use it for background, bio, and rules questions — anything that is not about the live race state. Answer only from what it returns.
  ```
- **Connect BOTH** data stores (`FE Rules` + `Driver and Team Profiles`) to this one tool.
  Set a sensible **grounding confidence** (LOW/MEDIUM to start) and keep the grounding
  heuristics filter on.

## Step 8 — Instructions v3 (final, + bios/rules + fused), then test

Replace the Instructions with the final version:

```text
Route each fan question to a tool and answer only from what the tool returns.

- Live race or in-race stats (current positions/standings, a car's speed, energy, or Attack Mode, gaps, what's happening now, recent overtakes or incidents, lap times, a driver's stats during this race): call {@TOOL: ask_race_data_ask_race_data} with the fan's question and answer from its answer field.
- Who a driver or team is (background, career, nationality, "who drives car N", team-mates, team history): search {@TOOL: fe_knowledge}.
- Formula E rules and how the sport works (Attack Mode, energy management, race format, the Tempelhof circuit, the Gen3 car, tyres, flags and safety cars): search {@TOOL: fe_knowledge}.
- Current, real-world, or off-dataset questions (news, the present-day championship, anything not specific to this replay): use {@TOOL: google_search}.
- When a question spans both the live race and history (e.g. comparing a car's current run to a driver's career form), use BOTH relevant tools and present what each shows; if a direct numeric comparison isn't possible, give both sides and say so rather than refusing.

Grounding (non-negotiable):
- Answer only from tool results. Never state race facts, results, statistics, driver or team details, or rules from your own knowledge.
- If no tool can answer, say you don't have that information. Do not guess or fill gaps from memory.
- Base data-store and Search answers on the retrieved passages, and keep their citations.

Time-honesty (non-negotiable):
- The race is a live replay. {@TOOL: ask_race_data_ask_race_data} is time-honest and refuses questions about the future ("who wins?", "who's on the podium?", "how does it end?"). When it refuses, relay that refusal warmly and never reveal the result, the podium, or anything that hasn't happened yet — even if you think you know it, and even from Google Search.
- Questions about the OUTCOME of this event (the Berlin 2024 R9/R10 result, winner, podium, or finishing order) are always off-limits: treat them as spoilers and never answer them from any tool or from memory.
- The profiles and rules are spoiler-free background; never combine them, or use outside knowledge, to infer or hint at the race outcome.

Voice:
- Be an enthusiastic, concise second-screen Formula E companion. Lead with the answer in 1-3 sentences, use driver short names and car numbers, friendly, not formal.

Scope:
- Stay on Formula E and this race. Politely redirect unrelated requests back to the race.
```

**Test:** "Who is Mitch Evans?" and "What's Attack Mode?" → grounded from `fe_knowledge`
with citations · "How many career wins does da Costa have?" → `fe_knowledge` · the fused
question "How does car 13's pace right now compare with Evans' career form?" → uses both.

---

## Step 9 — Full regression + export

Run the whole set once more: the 7 routes above + the spoiler back-doors ("who wins?",
"who won Berlin 2024?") + an anti-hallucination probe ("what's da Costa's favourite food?"
→ should decline). Then **`exportApp`** the agent definition into `app_config/` so the
low-code build is in version control.

---

## What we learned building this live (so you don't rediscover it)

- **Tool reference token:** `{@TOOL: <toolName>_<operationId>}`. The OpenAPI tool's operation
  is also `ask_race_data`, so it reads doubled: `{@TOOL: ask_race_data_ask_race_data}`. Data
  store / search tools have no operation: `{@TOOL: fe_knowledge}`, `{@TOOL: google_search}`.
- **One data store tool over both stores** keeps routing simple and matches the instructions;
  the per-store retrieval precision is preserved at the store level.
- **Indexing overlap:** create the stores first, attach last — the ~10–15 min wait hides
  behind the rest of the build.
- **Citations** show the source doc's title but aren't clickable (the docs are `.txt` in GCS,
  no public URL) — still valid grounding proof.
- **Spoiler-robust:** with the time-honesty + outcome-off-limits lines, the agent refuses
  "who won Berlin 2024?" even though Google Search knows the answer — the product's whole point.
