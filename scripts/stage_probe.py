"""Tier A/B rehearsal probe — batch-runs the scripted demo questions for
the build-up progression's first two checkpoints and captures transcripts.

Re-run on event morning and after ANY model change (FE_MODEL escapes
included) — the Tier A and Tier B checkpoint beats are model-behavior
demos, and grades beat vibes.

  --stage a   Tier A condition: the scaffold prompt, NO tools. Grade each
              answer by hand: the beat works when the famous fact lands
              right and the granular facts are confidently invented.
  --stage b   Tier B condition: solution/scaffold as shipped (the one raw
              SQL tool). Watch for: both WINs correct <90s, the top-speed
              recovery, the Vergne set-piece answer wrong-with-a-straight-
              face, the future leak on \"right now.\"

WHERE: Cloud Shell, repo root, `source activate.sh` first. Needs only
GOOGLE_CLOUD_PROJECT + the BigQuery dataset (setup steps 1-2); the
simulator is not involved.

    python scripts/stage_probe.py --stage a
    python scripts/stage_probe.py --stage b

Transcripts land in stage_transcripts/. Runner mechanics mirror
scripts/agent_chat.py (one event loop, run_async, per-event timing); one
persistent session per stage, like a student's chat.
"""
from __future__ import annotations

# Repo-root bootstrap: solution/ resolves via the editable install in a
# normal activated shell, but this probe must also run on a clone where
# `pip install -e .` hasn't happened yet (event-morning haste). Put the
# repo root on sys.path unconditionally — harmless when installed.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from shared.script_env import require_venv

require_venv()

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path

_parser = argparse.ArgumentParser(description=__doc__)
_parser.add_argument("--stage", choices=["a", "b"], default="a")
_parser.add_argument("--max-response-chars", type=int, default=500)
ARGS = _parser.parse_args()

from google.adk.agents import Agent  # noqa: E402
from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types  # noqa: E402

from solution.scaffold import agent as scaffold_agent  # noqa: E402

if ARGS.stage == "b":
    root_agent = scaffold_agent.root_agent  # as shipped: one raw SQL tool
else:
    # Tier A condition: same Gen-1 instruction, zero tools — Gemini's own
    # knowledge. (The constants live in scaffold agent.py precisely so this
    # probe can import them; students write the same words inline.)
    root_agent = Agent(
        name="race_engineer",
        model=scaffold_agent.MODEL,
        description=scaffold_agent.ROOT_AGENT_DESCRIPTION,
        instruction=scaffold_agent.ROOT_AGENT_INSTRUCTION,
    )

APP_NAME = "stage_probe"
USER_ID = "rehearsal"
OUT_DIR = Path("stage_transcripts")

QUESTIONS: dict[str, list[tuple[str, str]]] = {
    "a": [
        ("famous-fact", "Who won this race, and where did we finish?"),
        ("granular-fact", "What lap did we take our first attack mode, and which scenario did we arm?"),
        ("invented-detail", "What was Cassidy's energy consumption percentage on lap 7?"),
        ("granular-now", "Where are we in the race right now — position and lap?"),
        ("aggregate", "How many overtakes happened in this race in total?"),
    ],
    "b": [
        ("WIN-fastest-lap", "What was our fastest lap of the race — lap number and time? We're car 13."),
        ("WIN-race-control", "What were the most important race control messages during the race?"),
        ("RECOVERY-top-speed", "What was our top speed on our fastest lap? We're car 13."),
        ("SETPIECE-overtakes", "How many times did we overtake Vergne? We're car 13, he's car 25."),
        ("LEAK-now", "Who is directly behind us right now?"),
    ],
}


def fmt(obj, limit: int) -> str:
    s = obj if isinstance(obj, str) else json.dumps(obj, default=str)
    return s if len(s) <= limit else s[:limit] + f"... (+{len(s) - limit} chars)"


async def ask(runner: InMemoryRunner, session_id: str, tag: str, question: str,
              limit: int, log) -> dict:
    msg = types.Content(role="user", parts=[types.Part(text=question)])
    t0 = time.monotonic()
    last = t0
    tool_calls = 0
    tool_errors = 0
    final: list[str] = []

    log(f"\n=== [{tag}] {question}")
    async for event in runner.run_async(user_id=USER_ID, session_id=session_id,
                                        new_message=msg):
        now = time.monotonic()
        gap, last = now - last, now
        for call in event.get_function_calls():
            tool_calls += 1
            log(f"  [+{now - t0:5.1f}s  llm {gap:5.1f}s] ▶ {call.name}({fmt(dict(call.args or {}), 400)})")
        for fr in event.get_function_responses():
            if isinstance(fr.response, dict) and "error" in str(fr.response.get("result", fr.response)):
                tool_errors += 1
            log(f"  [+{now - t0:5.1f}s tool {gap:5.1f}s] ◀ {fr.name}: {fmt(fr.response, limit)}")
        if event.is_final_response() and event.content and event.content.parts:
            for part in event.content.parts:
                if getattr(part, "text", None):
                    final.append(part.text)

    wall = time.monotonic() - t0
    answer = "".join(final).strip() or "(no text response)"
    log(f"\nENGINEER: {answer}")
    log(f"── {wall:.1f}s wall | {tool_calls} tool calls | {tool_errors} tool errors")
    return {"tag": tag, "wall_s": round(wall, 1), "tool_calls": tool_calls,
            "tool_errors": tool_errors}


async def amain() -> None:
    stage = ARGS.stage
    OUT_DIR.mkdir(exist_ok=True)
    out_path = OUT_DIR / f"stage_{stage}_{time.strftime('%H%M%S')}.txt"
    lines: list[str] = []

    def log(s: str) -> None:
        print(s)
        lines.append(s)

    log(f"Stage probe — Tier {stage.upper()} condition | model "
        f"{os.environ.get('FE_MODEL', 'gemini-3.5-flash')} | "
        f"tools on agent: {len(root_agent.tools)}")

    runner = InMemoryRunner(agent=root_agent, app_name=APP_NAME)
    session_id = f"probe-{uuid.uuid4().hex[:8]}"
    await runner.session_service.create_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session_id)

    results = []
    for tag, q in QUESTIONS[stage]:
        results.append(await ask(runner, session_id, tag, q,
                                 ARGS.max_response_chars, log))

    log("\n" + "=" * 72)
    log(f"SUMMARY — Tier {stage.upper()} condition")
    for r in results:
        log(f"  {r['tag']:<20} {r['wall_s']:6.1f}s  {r['tool_calls']} tools  "
            f"{r['tool_errors']} errors")
    log(f"  {'TOTAL':<20} {sum(r['wall_s'] for r in results):6.1f}s")

    if stage == "a":
        log("\nGRADE: famous-fact should land RIGHT; the rest confidently "
            "invented, same delivery. If the model starts refusing instead, "
            "the beat still works — narrate it as 'it knows what it doesn't "
            "know is coming.' If granular facts come back CORRECT, the model "
            "changed — re-stage the Tier A beat before the event.")
    else:
        log("\nGRADE: WINs correct <90s; top-speed recovers via "
            "top_speed_per_lap; the Vergne answer should be WRONG with an "
            "invented rationalization (the set-piece — if it comes back "
            "RIGHT, the model changed and the set-piece needs re-staging); "
            "the 'right now' answer reads the final lap (the leak that "
            "motivates Tier D).")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nTranscript written: {out_path}")


if __name__ == "__main__":
    if sys.version_info < (3, 10):
        print("Python 3.10+ required", file=sys.stderr)
        sys.exit(1)
    asyncio.run(amain())
