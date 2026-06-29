# Wiring the race-data subagent into CX Agent Studio

Step-by-step to make a CX (Conversational Agents / CX Agent Studio) agent call
the deployed `race-data-subagent` as an **OpenAPI tool**. This is the real-build
version of `spike/cx_openapi_spike/CX_WIRING.md` (which was written for the spike
stub). The schema is `openapi_ask_race_data.yaml` in this folder (inlined in the
appendix below).

## Prerequisites

- The subagent is deployed and answering (run `deploy/RUNBOOK_race_data_subagent.md`
  through the curl checks first — live-moment answers, "who wins?" refuses).
- `DETERMINISTIC=0` if you want real grounded answers in CX (deterministic mode
  also works for a pure wire test, but returns the `[deterministic]` placeholder).
- The CES service agent has `run.invoker` on the service — the deploy script
  grants this. (If CX 401/403s, see Troubleshooting.)

## 0. Get your values

After the subagent is deployed, `source activate.sh` exports **`$SUBAGENT_URL`** (the base
Cloud Run URL) automatically — same discovery it does for `TOOLBOX_URL`:

```bash
source activate.sh
echo "$SUBAGENT_URL"     # e.g. https://race-data-subagent-abc123-uc.a.run.app
```

Or fetch it directly:

```bash
gcloud run services describe race-data-subagent --region "$REGION" --format='value(status.url)'
```

You'll paste this URL into the schema's `servers:` block (no trailing slash).

## 1. Open CX Agent Studio

CX Agent Studio is **not** in the main Cloud Console — go to
**`ces.cloud.google.com`**, pick this project, and open (or create) your agent/app.
First-time creation takes a few minutes, then the designer opens.

## 2. Create the OpenAPI tool

1. On the agent node, click **+** → **"Add new abilities with tools"** (or open
   **Tools**), then **+ Create / Add**.
2. Tool type: **OpenAPI**.
3. Name: `ask_race_data`.
4. **Description** (this is what the orchestrator LLM reads to decide *when* to
   call the tool — make it specific and time-honest):

   > Authoritative source for Formula E race facts about the Berlin 2024 Round 10
   > E-Prix replay and 10 seasons of driver/team history. Call it for any question
   > about the live race right now (positions, standings, a car's speed, energy, or
   > Attack Mode, recent overtakes or incidents) or recorded race and career
   > statistics (lap times, top speeds, energy use, head-to-head overtakes, career
   > wins/podiums/points). Answers are time-honest — bounded to the replay's current
   > moment — so it never reveals results or events that haven't happened yet. Always
   > use this tool for race facts rather than answering from your own knowledge.

5. **Schema:** paste the contents of `openapi_ask_race_data.yaml` (appendix
   below), with `SERVICE_URL` replaced by your Cloud Run URL. It is intentionally
   a **single operation** — CX allows exactly one operation per OpenAPI tool.

## 3. Authentication — Service agent ID token

- **Authentication:** choose **Service agent ID token**.
- This makes CX call the service as
  `service-{PROJECT_NUMBER}@gcp-sa-ces.iam.gserviceaccount.com` — the identity the
  deploy script granted `run.invoker`. No key, no service-account file.
- Same-project Cloud Run needs nothing beyond that grant. (Cross-project would
  also need the ID-token audience set to the service URL.)

Save. If the tool dialog offers a **Test / Try-it**, send
`{"question":"how is car 13 doing right now?"}` and confirm a 200 with
`refused_future: false`.

## 4. Tell the agent to use the tool (instructions + grounding)

On the agent node: **+** → **"Add instructions"**. Add something like:

> When the user asks anything about the race, a car, the standings, statistics,
> a driver's history, or what's happening "right now", call
> `{@TOOL: ask_race_data_ask_race_data}` with their question and answer **only**
> from the tool's `answer` field. Never state race facts (positions, energy,
> winners, history) from your own knowledge. If the tool declines to answer
> something about the future, relay that refusal — never reveal what hasn't
> happened yet.

Two things to note:

- **`{@TOOL: ask_race_data_ask_race_data}`** is the reference format
  `{@TOOL: <toolName>_<operationId>}` — tool `ask_race_data` + operation
  `ask_race_data`.
- **Grounding is mandatory.** In the spike, with no such instruction, the CX
  orchestrator LLM embellished its replies with invented positions/driver facts
  from training data. The subagent now returns those as real data; the
  instruction above forces CX to use them and not improvise. (Fuller grounding —
  data stores + Google Search for rules/profiles — is the cx_concierge build, #5.)

Save / re-train if prompted.

## 5. (Optional) Execution mode — async / long-running

The real LLM + tools round trip is ~7–9s (a cold instance's first call is
slower). CX's synchronous ideal is ~5s; async/long-running covers ~5–60s. The
spike tolerated a 6.7s tool call synchronously with no setting, so this is
**advisory headroom**, not required. If a tool-use/execution setting is present
and latency climbs, set it to **asynchronous / long-running**.

## 6. Test in the simulator

Open the **Simulator** / preview:

1. **Live moment:** "How's car 13 right now?" → the agent calls `ask_race_data`
   and answers with the current standings. Check the tool-call trace shows it hit
   your Cloud Run service. ✅ discovery + auth + live answer.
2. **Time-honesty:** "Who wins the race?" → must decline to spoil. ✅ future leak
   blocked.
3. **Career:** "How has da Costa done over recent seasons?" → answers from
   BigQuery career data (LLM mode), bounded to now. ✅ "then" path.

## Troubleshooting

- **401 / 403 from the tool.** The CES service agent lacks `run.invoker`, or it
  doesn't exist yet. It's created on first CX use — open CX in this project once,
  then rerun `deploy/deploy_race_data_subagent.sh` (it forces the identity and
  retries the grant). Confirm `PROJECT_NUMBER` is right.
- **Answer looks invented / wrong positions.** The grounding instruction (step 4)
  is missing or weak — CX is answering from its own model. Tighten it to "answer
  only from the tool's `answer` field."
- **`mode: "llm-error"` in the response.** The agent run failed; the `error`
  field names the exception and a full traceback is in
  `gcloud run services logs read race-data-subagent --region $REGION`. Common
  causes: model/location (see `KNOWN_FIXES.md` #10).
- **CX rejects the schema ("one operation").** You pasted more than one path/op —
  use exactly `openapi_ask_race_data.yaml` (one POST operation). Do **not** paste
  the service's auto `/openapi.json` (in LLM mode it lists ADK's many endpoints).

---

## Appendix — `openapi_ask_race_data.yaml`

Replace `SERVICE_URL` with your Cloud Run URL (no trailing slash). This is the
exact file in this folder.

```yaml
openapi: 3.0.0
info:
  title: Race-Data Subagent
  version: "1.0.0"
  description: Answers Formula E race-data questions, bounded to the replay's current moment.
servers:
  - url: SERVICE_URL
paths:
  /ask_race_data:
    post:
      operationId: ask_race_data
      summary: Ask a race-data question about the Berlin 2024 E-Prix replay.
      description: >
        Answers a fan's race or statistics question about Berlin 2024 Round 10
        (live "now" + recorded "then") and 10 seasons of driver/team career
        history, bounded to the replay's current moment (time-honest — never
        reveals what hasn't happened yet).
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [question]
              properties:
                question:
                  type: string
                  description: The fan's race-data question.
      responses:
        "200":
          description: The agent's answer.
          content:
            application/json:
              schema:
                type: object
                properties:
                  answer:
                    type: string
                    description: The answer, bounded to the current moment.
                  race_time_s:
                    type: integer
                    description: Replay seconds since green flag.
                  race_wall_time_ns:
                    type: integer
                    format: int64
                    description: Computed 2024 wall-clock ns of the current moment.
                  now_source:
                    type: string
                    description: "'firestore' (live) or 'canned' (fallback)."
                  refused_future:
                    type: boolean
                    description: True if a future/spoiler question was refused.
                  mode:
                    type: string
                    description: "'deterministic', 'llm', or 'llm-error'."
```
